import logging
import re
import base64
import hashlib
from typing import Any
import secrets
import random
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
import jwt
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import auth_dep, db_dep, ensure_user_exists
from app.core.config import get_settings
from app.core.rate_limit import check_registration_captcha_rate_limit, check_registration_rate_limit
from app.core.security import AuthContext, _allowed_issuers, _get_keycloak_jwks, _jwk_signing_key
from app.models import ProviderSetting, Tenant

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)
_redis = Redis.from_url(settings.redis_url, decode_responses=True)
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
TRUSTED_ORIGINS = {x.strip().rstrip("/") for x in settings.cors_origins.split(",") if x.strip()}
OIDC_ASYMMETRIC_ALGS = {
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
}


class OIDCExchangeIn(BaseModel):
    code: str
    code_verifier: str
    nonce: str
    redirect_uri: str | None = None


class OIDCRefreshOut(BaseModel):
    detail: str


class RegisterIn(BaseModel):
    email: str
    password: str
    captcha_token: str | None = None
    captcha_id: str | None = None
    captcha_answer: str | None = None


class RegisterOut(BaseModel):
    detail: str


class CaptchaChallengeOut(BaseModel):
    captcha_id: str
    prompt: str


class RegisterConfigOut(BaseModel):
    captcha_required: bool
    captcha_provider: str
    builtin_captcha: bool
    captcha_site_key: str | None = None


REGISTER_NEUTRAL_DETAIL = "If registration is available, we will send further instructions to the provided email address."


def _alg_hash_name(alg: str) -> str:
    upper = alg.upper()
    if upper.endswith("256"):
        return "sha256"
    if upper.endswith("384"):
        return "sha384"
    if upper.endswith("512"):
        return "sha512"
    raise HTTPException(status_code=401, detail="Unsupported token hash algorithm")


def _expected_at_hash(access_token: str, alg: str) -> str:
    digest = hashlib.new(_alg_hash_name(alg), access_token.encode("utf-8")).digest()
    half = digest[: len(digest) // 2]
    return base64.urlsafe_b64encode(half).rstrip(b"=").decode("ascii")


def _cookie_options(max_age: int | None = None) -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        "samesite": settings.auth_cookie_samesite,
        "path": "/",
        "max_age": max_age,
    }


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str | None,
    expires_in: int | None,
    id_token: str | None = None,
):
    response.set_cookie("access_token", access_token, **_cookie_options(max_age=expires_in or 300))
    if id_token:
        response.set_cookie("id_token", id_token, **_cookie_options(max_age=expires_in or 300))
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
    response.delete_cookie("id_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


async def _validate_nonce(id_token: str | None, expected_nonce: str, access_token: str | None = None) -> None:
    if not id_token:
        raise HTTPException(status_code=401, detail="Missing id_token")
    try:
        unverified_header = jwt.get_unverified_header(id_token)
        kid = unverified_header.get("kid")
        # Backward-compatible fallback for tests/mocks that omit `alg`.
        alg = str(unverified_header.get("alg") or "RS256").upper()
        if alg not in OIDC_ASYMMETRIC_ALGS:
            raise HTTPException(status_code=401, detail="Invalid id_token algorithm")
        jwks = await _get_keycloak_jwks()
        key = _jwk_signing_key(jwks, kid)
        if key is None and kid:
            jwks = await _get_keycloak_jwks(force_refresh=True)
            key = _jwk_signing_key(jwks, kid)
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid id_token key")
        decode_options = {"verify_aud": False, "verify_iss": False}
        try:
            decode_kwargs = {
                "key": key,
                "algorithms": [alg],
                "options": decode_options,
            }
            claims = jwt.decode(id_token, **decode_kwargs)
        except Exception:
            # Retry once with force-refreshed JWKS in case key material rotated in-place.
            jwks = await _get_keycloak_jwks(force_refresh=True)
            key = _jwk_signing_key(jwks, kid)
            if key is None:
                raise HTTPException(status_code=401, detail="Invalid id_token key")
            decode_kwargs = {
                "key": key,
                "algorithms": [alg],
                "options": decode_options,
            }
            claims = jwt.decode(id_token, **decode_kwargs)
        token_issuer = str(claims.get("iss") or "").rstrip("/")
        if token_issuer not in _allowed_issuers(settings):
            raise HTTPException(status_code=401, detail="Invalid id_token issuer")
        expected_client_id = settings.oidc_frontend_client_id
        aud = claims.get("aud")
        azp = claims.get("azp")
        aud_ok = False
        if isinstance(aud, str):
            aud_ok = aud == expected_client_id
        elif isinstance(aud, list):
            aud_ok = expected_client_id in [str(x) for x in aud]
        if not aud_ok and azp == expected_client_id:
            aud_ok = True
        if not aud_ok:
            raise HTTPException(status_code=401, detail="Invalid id_token audience")
        if access_token:
            token_at_hash = str(claims.get("at_hash") or "").strip()
            if not token_at_hash:
                raise HTTPException(status_code=401, detail="Missing id_token at_hash")
            if token_at_hash != _expected_at_hash(access_token, alg):
                raise HTTPException(status_code=401, detail="Invalid id_token at_hash")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "ID token validation failed during nonce check: %s: %s",
            exc.__class__.__name__,
            str(exc)[:300],
        )
        raise HTTPException(status_code=401, detail="Invalid id_token") from exc
    if claims.get("nonce") != expected_nonce:
        raise HTTPException(status_code=401, detail="Invalid nonce")


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254:
        raise HTTPException(status_code=400, detail="Invalid email address")
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    local_part = email.split("@", 1)[0]
    if len(local_part) > 64:
        raise HTTPException(status_code=400, detail="Invalid email address")
    return email


def _default_profile_name(email: str) -> str:
    local_part = email.split("@", 1)[0].strip()
    return local_part or "user"


def _validate_password(value: str) -> str:
    password = value.strip()
    if len(password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters long")
    if not re.search(r"[a-z]", password):
        raise HTTPException(status_code=400, detail="Password must contain lowercase letters")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(status_code=400, detail="Password must contain uppercase letters")
    if not re.search(r"[0-9]", password):
        raise HTTPException(status_code=400, detail="Password must contain digits")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise HTTPException(status_code=400, detail="Password must contain a special character")
    return password


def _resolve_registration_tenant(db: Session) -> str:
    raw_default = (settings.default_tenant_id or "").strip()
    if raw_default:
        try:
            tenant_id = str(uuid.UUID(raw_default))
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is invalid") from exc
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID was not found in the database")
        return tenant_id

    tenants = list(db.scalars(select(Tenant).order_by(Tenant.created_at.asc())))
    if not tenants:
        raise HTTPException(status_code=500, detail="No tenant is available in the database for registration")
    if len(tenants) > 1:
        raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is required for multi-tenant registration")
    return str(tenants[0].id)


async def _keycloak_admin_token() -> str:
    if not settings.keycloak_admin or not settings.keycloak_admin_password:
        raise HTTPException(status_code=500, detail="KEYCLOAK_ADMIN/KEYCLOAK_ADMIN_PASSWORD are not configured")
    token_url = (
        f"{settings.keycloak_server_url}/realms/{settings.keycloak_admin_realm}/protocol/openid-connect/token"
    )
    form = {
        "grant_type": "password",
        "client_id": settings.keycloak_admin_client_id,
        "username": settings.keycloak_admin,
        "password": settings.keycloak_admin_password,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_url, data=form)
    if resp.status_code >= 400:
        logger.error("Keycloak admin token request failed: status=%s body=%s", resp.status_code, resp.text[:300])
        raise HTTPException(status_code=502, detail="Failed to obtain Keycloak admin token")
    token = resp.json().get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="Keycloak admin token is empty")
    return str(token)


async def _get_or_create_user_role(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    role_url = f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/roles/user"
    role_resp = await client.get(role_url, headers=headers)
    if role_resp.status_code == 200:
        return role_resp.json()
    if role_resp.status_code != 404:
        raise HTTPException(status_code=502, detail="Failed to read the user role from Keycloak")

    create_resp = await client.post(
        f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/roles",
        headers=headers,
        json={"name": "user"},
    )
    if create_resp.status_code not in (201, 204, 409):
        raise HTTPException(status_code=502, detail="Failed to create the user role in Keycloak")

    role_resp = await client.get(role_url, headers=headers)
    if role_resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch the user role after creation")
    return role_resp.json()


async def _create_keycloak_user(email: str, password: str, tenant_id: str) -> bool:
    token = await _keycloak_admin_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    users_url = f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/users"
    require_admin_approval = settings.register_requires_admin_approval
    require_email_verification = settings.register_require_email_verification and not require_admin_approval
    email_verified = not settings.register_require_email_verification
    profile_name = _default_profile_name(email)
    payload = {
        "username": email,
        "email": email,
        "firstName": profile_name,
        "lastName": profile_name,
        "enabled": not require_admin_approval,
        "emailVerified": email_verified,
        "attributes": {"tenant_id": [tenant_id]},
        "credentials": [{"type": "password", "value": password, "temporary": False}],
        "requiredActions": ["VERIFY_EMAIL"] if require_email_verification else [],
    }

    async with httpx.AsyncClient(timeout=20) as client:
        create_resp = await client.post(users_url, headers=headers, json=payload)
        if create_resp.status_code == 409:
            logger.info("Registration attempted for existing user")
            return False
        if create_resp.status_code not in (201, 204):
            logger.error("Keycloak user create failed: status=%s body=%s", create_resp.status_code, create_resp.text[:300])
            raise HTTPException(status_code=502, detail="Failed to create user in Keycloak")

        users_resp = await client.get(users_url, headers=headers, params={"exact": "true", "username": email})
        if users_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Failed to verify user in Keycloak")
        users = users_resp.json() or []
        if not users:
            raise HTTPException(status_code=502, detail="User was created but could not be found in Keycloak")
        user_id = users[0]["id"]

        user_role = await _get_or_create_user_role(client, headers)
        map_resp = await client.post(
            f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/users/{user_id}/role-mappings/realm",
            headers=headers,
            json=[user_role],
        )
        if map_resp.status_code not in (204, 409):
            raise HTTPException(status_code=502, detail="Failed to assign the user role in Keycloak")

        if require_email_verification:
            verify_resp = await client.put(
                f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/users/{user_id}/execute-actions-email",
                headers=headers,
                params={"client_id": settings.oidc_frontend_client_id},
                json=["VERIFY_EMAIL"],
            )
            # If SMTP is not configured in Keycloak this can fail; surface explicit error.
            if verify_resp.status_code not in (200, 204):
                logger.error(
                    "Keycloak verify email dispatch failed: status=%s body=%s",
                    verify_resp.status_code,
                    verify_resp.text[:300],
                )
                raise HTTPException(status_code=502, detail="Failed to send email verification message")
    return True


def _request_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _captcha_cache_key(captcha_id: str) -> str:
    return f"register:captcha:{captcha_id}"


def _new_builtin_captcha() -> tuple[str, str, str]:
    left = random.randint(2, 9)
    right = random.randint(2, 9)
    op = random.choice(["+", "-", "*"])
    if op == "-" and right > left:
        left, right = right, left
    answer = str(left + right if op == "+" else left - right if op == "-" else left * right)
    prompt = f"Enter the result: {left} {op} {right}"
    captcha_id = secrets.token_urlsafe(18)
    return captcha_id, prompt, answer


def _verify_builtin_captcha(captcha_id: str, captcha_answer: str) -> None:
    key = _captcha_cache_key(captcha_id)
    try:
        expected = _redis.get(key)
        _redis.delete(key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="CAPTCHA service is temporarily unavailable") from exc
    if not expected:
        raise HTTPException(status_code=400, detail="CAPTCHA has expired or was already used")
    if captcha_answer.strip() != expected.strip():
        raise HTTPException(status_code=400, detail="Incorrect CAPTCHA answer")


async def _verify_turnstile(captcha_token: str, request: Request) -> None:
    if not settings.turnstile_secret_key:
        raise HTTPException(status_code=500, detail="TURNSTILE_SECRET_KEY is not configured")
    form = {
        "secret": settings.turnstile_secret_key,
        "response": captcha_token,
        "remoteip": _request_ip(request),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=form)
    if resp.status_code >= 400:
        raise HTTPException(status_code=503, detail="CAPTCHA service is temporarily unavailable")
    data = resp.json()
    if not data.get("success"):
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed")


async def _verify_hcaptcha(captcha_token: str, request: Request) -> None:
    if not settings.hcaptcha_secret_key:
        raise HTTPException(status_code=500, detail="HCAPTCHA_SECRET_KEY is not configured")
    form = {
        "secret": settings.hcaptcha_secret_key,
        "response": captcha_token,
        "remoteip": _request_ip(request),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post("https://hcaptcha.com/siteverify", data=form)
    if resp.status_code >= 400:
        raise HTTPException(status_code=503, detail="CAPTCHA service is temporarily unavailable")
    data = resp.json()
    if not data.get("success"):
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed")


async def _verify_captcha(captcha_token: str, request: Request) -> None:
    provider = (settings.register_captcha_provider or "").strip().lower()
    if provider in {"builtin", "selfhosted", "self-hosted", "local"}:
        raise HTTPException(status_code=500, detail="Use captcha_id/captcha_answer for builtin CAPTCHA")
    if provider in {"turnstile", "cloudflare"}:
        await _verify_turnstile(captcha_token, request)
        return
    if provider in {"hcaptcha", "h-captcha"}:
        await _verify_hcaptcha(captcha_token, request)
        return
    raise HTTPException(
        status_code=500,
        detail="Unsupported REGISTER_CAPTCHA_PROVIDER",
    )


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


@router.get("/register/captcha", response_model=CaptchaChallengeOut)
def register_captcha(request: Request) -> CaptchaChallengeOut:
    provider = (settings.register_captcha_provider or "").strip().lower()
    if provider not in {"builtin", "selfhosted", "self-hosted", "local"}:
        raise HTTPException(status_code=400, detail="This endpoint is available only for builtin CAPTCHA")
    check_registration_captcha_rate_limit(request)
    captcha_id, prompt, answer = _new_builtin_captcha()
    ttl = max(30, int(settings.register_builtin_captcha_ttl_s))
    try:
        _redis.setex(_captcha_cache_key(captcha_id), ttl, answer)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="CAPTCHA service is temporarily unavailable") from exc
    return CaptchaChallengeOut(captcha_id=captcha_id, prompt=prompt)


@router.get("/register/config", response_model=RegisterConfigOut)
def register_config() -> RegisterConfigOut:
    provider = (settings.register_captcha_provider or "builtin").strip().lower()
    builtin_captcha = provider in {"builtin", "selfhosted", "self-hosted", "local"}
    captcha_site_key: str | None = None
    if not builtin_captcha:
        if provider == "hcaptcha":
            captcha_site_key = (settings.register_hcaptcha_site_key or "").strip() or None
        elif provider == "turnstile":
            captcha_site_key = (settings.register_turnstile_site_key or "").strip() or None
    return RegisterConfigOut(
        captcha_required=bool(settings.register_enforce_captcha),
        captcha_provider=provider,
        builtin_captcha=builtin_captcha,
        captcha_site_key=captcha_site_key,
    )


@router.post("/oidc/exchange")
async def oidc_exchange(payload: OIDCExchangeIn, response: Response):
    redirect_uri = settings.oidc_frontend_redirect_uri
    incoming_redirect = (payload.redirect_uri or "").strip()
    if incoming_redirect and incoming_redirect.rstrip("/") != redirect_uri.rstrip("/"):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")
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
    await _validate_nonce(
        id_token=data.get("id_token"),
        expected_nonce=payload.nonce,
        access_token=data.get("access_token"),
    )
    _set_auth_cookies(
        response=response,
        access_token=str(data.get("access_token", "")),
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 300)),
        id_token=data.get("id_token"),
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
        id_token=data.get("id_token"),
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
    if revoke_error:
        error_response = JSONResponse(
            status_code=502,
            content={"detail": f"Logout completed locally, token revoke failed: {revoke_error}"},
        )
        _clear_auth_cookies(error_response)
        return error_response
    _clear_auth_cookies(response)
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


@router.post("/register", response_model=RegisterOut, status_code=202)
async def register(payload: RegisterIn, request: Request, db: Session = Depends(db_dep)):
    _validate_origin_referer(request)
    email = _normalize_email(payload.email)
    check_registration_rate_limit(request, email)
    password = _validate_password(payload.password)
    if settings.register_enforce_captcha:
        provider = (settings.register_captcha_provider or "").strip().lower()
        if provider in {"builtin", "selfhosted", "self-hosted", "local"}:
            captcha_id = (payload.captcha_id or "").strip()
            captcha_answer = (payload.captcha_answer or "").strip()
            if not captcha_id or not captcha_answer:
                raise HTTPException(status_code=400, detail="CAPTCHA is required")
            _verify_builtin_captcha(captcha_id=captcha_id, captcha_answer=captcha_answer)
        else:
            token = (payload.captcha_token or "").strip()
            if not token:
                raise HTTPException(status_code=400, detail="Complete the CAPTCHA challenge")
            await _verify_captcha(token, request)
    tenant_id = _resolve_registration_tenant(db)
    await _create_keycloak_user(email=email, password=password, tenant_id=tenant_id)
    return RegisterOut(detail=REGISTER_NEUTRAL_DETAIL)
