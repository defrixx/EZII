import logging
from typing import Any
import secrets
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from jose import jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import auth_dep, db_dep, ensure_user_exists
from app.core.config import get_settings
from app.core.security import AuthContext
from app.models import ProviderSetting

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
TRUSTED_ORIGINS = {x.strip().rstrip("/") for x in settings.cors_origins.split(",") if x.strip()}


class OIDCExchangeIn(BaseModel):
    code: str
    code_verifier: str
    nonce: str
    redirect_uri: str | None = None


class OIDCRefreshOut(BaseModel):
    detail: str


def _cookie_options(max_age: int | None = None) -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        "samesite": settings.auth_cookie_samesite,
        "path": "/",
        "max_age": max_age,
    }


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str | None, expires_in: int | None):
    response.set_cookie("access_token", access_token, **_cookie_options(max_age=expires_in or 300))
    if refresh_token:
        response.set_cookie("refresh_token", refresh_token, **_cookie_options(max_age=60 * 60 * 24 * 30))


def _set_csrf_cookie(response: Response):
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
        max_age=60 * 60 * 24 * 30,
    )


def _validate_csrf(request: Request):
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def _validate_origin_referer(request: Request):
    origin = (request.headers.get("origin") or "").rstrip("/")
    referer = request.headers.get("referer") or ""
    referer_origin = ""
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            referer_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    if not origin and not referer_origin:
        raise HTTPException(status_code=403, detail="Missing Origin/Referer")
    if origin and origin not in TRUSTED_ORIGINS:
        raise HTTPException(status_code=403, detail="Untrusted Origin")
    if referer_origin and referer_origin not in TRUSTED_ORIGINS:
        raise HTTPException(status_code=403, detail="Untrusted Referer")


def _clear_auth_cookies(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def _validate_nonce(id_token: str | None, expected_nonce: str) -> None:
    if not id_token:
        raise HTTPException(status_code=401, detail="Missing id_token")
    claims = jwt.get_unverified_claims(id_token)
    if claims.get("nonce") != expected_nonce:
        raise HTTPException(status_code=401, detail="Invalid nonce")


async def _revoke_tokens(refresh_token: str | None, access_token: str | None) -> None:
    if not refresh_token and not access_token:
        return

    revoke_url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/revoke"
    logout_url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/logout"
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=15) as client:
        if refresh_token:
            refresh_revoke = await client.post(
                revoke_url,
                data={
                    "client_id": settings.oidc_frontend_client_id,
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                },
            )
            if refresh_revoke.status_code >= 400:
                errors.append(f"refresh revoke failed ({refresh_revoke.status_code})")

            session_logout = await client.post(
                logout_url,
                data={
                    "client_id": settings.oidc_frontend_client_id,
                    "refresh_token": refresh_token,
                },
            )
            if session_logout.status_code >= 400:
                errors.append(f"session logout failed ({session_logout.status_code})")

        if access_token:
            access_revoke = await client.post(
                revoke_url,
                data={
                    "client_id": settings.oidc_frontend_client_id,
                    "token": access_token,
                    "token_type_hint": "access_token",
                },
            )
            # Access token revocation support can vary by provider setup; refresh/session revoke remains mandatory.
            if access_revoke.status_code >= 400:
                logger.warning("Access token revoke failed with status %s", access_revoke.status_code)

    if errors:
        raise HTTPException(status_code=502, detail="; ".join(errors))


@router.post("/oidc/exchange")
async def oidc_exchange(payload: OIDCExchangeIn, response: Response):
    redirect_uri = payload.redirect_uri or settings.oidc_frontend_redirect_uri
    token_url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"
    form = {
        "grant_type": "authorization_code",
        "client_id": settings.oidc_frontend_client_id,
        "code": payload.code,
        "redirect_uri": redirect_uri,
        "code_verifier": payload.code_verifier,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_url, data=form)
    if resp.status_code >= 400:
        raise HTTPException(status_code=401, detail="OIDC code exchange failed")

    data = resp.json()
    _validate_nonce(data.get("id_token"), payload.nonce)
    _set_auth_cookies(
        response=response,
        access_token=str(data.get("access_token", "")),
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 300)),
    )
    _set_csrf_cookie(response)
    return {"detail": "ok"}


@router.post("/oidc/refresh", response_model=OIDCRefreshOut)
async def oidc_refresh(request: Request, response: Response):
    _validate_origin_referer(request)
    _validate_csrf(request)
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        logger.warning("OIDC refresh rejected: missing refresh_token cookie")
        error_response = JSONResponse(status_code=401, content={"detail": "Missing refresh token"})
        _clear_auth_cookies(error_response)
        return error_response

    token_url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"
    form = {
        "grant_type": "refresh_token",
        "client_id": settings.oidc_frontend_client_id,
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_url, data=form)
    if resp.status_code >= 400:
        logger.warning("OIDC refresh failed with status=%s body=%s", resp.status_code, resp.text[:300])
        error_response = JSONResponse(status_code=401, content={"detail": "OIDC refresh failed"})
        _clear_auth_cookies(error_response)
        return error_response

    data = resp.json()
    _set_auth_cookies(
        response=response,
        access_token=str(data.get("access_token", "")),
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 300)),
    )
    _set_csrf_cookie(response)
    return OIDCRefreshOut(detail="ok")


@router.post("/logout")
async def logout(request: Request, response: Response):
    _validate_origin_referer(request)
    _validate_csrf(request)
    refresh_token = request.cookies.get("refresh_token")
    access_token = request.cookies.get("access_token")
    revoke_error: str | None = None
    try:
        await _revoke_tokens(refresh_token=refresh_token, access_token=access_token)
    except HTTPException as exc:
        revoke_error = str(exc.detail)
    _clear_auth_cookies(response)
    if revoke_error:
        raise HTTPException(status_code=502, detail=f"Logout completed locally, token revoke failed: {revoke_error}")
    return {"detail": "ok"}


@router.get("/session")
def session_info(ctx: AuthContext = Depends(auth_dep), db: Session = Depends(db_dep)):
    ensure_user_exists(db, ctx)
    provider_settings = db.scalar(select(ProviderSetting).where(ProviderSetting.tenant_id == ctx.tenant_id))
    return {
        "user_id": ctx.user_id,
        "tenant_id": ctx.tenant_id,
        "email": ctx.email,
        "role": ctx.role,
        "show_source_tags": provider_settings.show_source_tags if provider_settings else True,
    }
