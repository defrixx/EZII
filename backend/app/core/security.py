import logging
import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
import jwt
from jwt import PyJWK
from app.core.config import get_settings

bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_expire_at: float = 0.0
_jwks_lock = asyncio.Lock()
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


def _fallback_identity_email(sub: str) -> str:
    stable = str(sub).strip() or "unknown-user"
    return f"{stable}@keycloak.local"


@dataclass
class AuthContext:
    user_id: str
    tenant_id: str
    email: str
    role: str


def _extract_role(payload: dict[str, Any]) -> str:
    roles: set[str] = set()

    realm_roles = payload.get("realm_access", {}).get("roles", [])
    if isinstance(realm_roles, list):
        roles.update(str(r) for r in realm_roles)

    if "admin" in roles:
        return "admin"
    if "user" in roles:
        return "user"
    raise HTTPException(status_code=403, detail="Missing required role")


def _allowed_issuers(settings) -> set[str]:
    raw = settings.keycloak_issuer.rstrip("/")
    realm_suffix = f"/realms/{settings.keycloak_realm}"
    if raw.endswith(realm_suffix):
        base = raw[: -len(realm_suffix)]
    else:
        base = raw
    return {raw, f"{base.rstrip('/')}{realm_suffix}"}


def _jwk_signing_key(jwks: dict[str, Any], kid: str | None) -> Any | None:
    if not kid:
        return None
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not key:
        return None
    return PyJWK.from_dict(key).key


async def _get_keycloak_jwks(force_refresh: bool = False) -> dict:
    global _jwks_cache, _jwks_cache_expire_at
    settings = get_settings()
    now = time.monotonic()
    if not force_refresh and _jwks_cache and now < _jwks_cache_expire_at:
        return _jwks_cache

    url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"
    async with _jwks_lock:
        now = time.monotonic()
        if not force_refresh and _jwks_cache and now < _jwks_cache_expire_at:
            return _jwks_cache
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            if _jwks_cache:
                logger.warning("JWKS fetch failed, using stale cache")
                return _jwks_cache
            raise

        _jwks_cache = data
        _jwks_cache_expire_at = time.monotonic() + max(1, settings.keycloak_jwks_ttl_s)
        return data


async def _fetch_userinfo(access_token: str) -> dict[str, Any] | None:
    settings = get_settings()
    url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/userinfo"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthContext:
    settings = get_settings()

    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        async def _decode_token(
            raw_token: str,
            audience: str,
            allow_force_refresh: bool = True,
        ) -> dict[str, Any]:
            unverified_header = jwt.get_unverified_header(raw_token)
            kid = unverified_header.get("kid")
            alg = str(unverified_header.get("alg") or "RS256").upper()
            if alg not in OIDC_ASYMMETRIC_ALGS:
                raise HTTPException(status_code=401, detail="Invalid token algorithm")
            jwks = await _get_keycloak_jwks()
            key = _jwk_signing_key(jwks, kid)
            if key is None and kid and allow_force_refresh:
                # Handle Keycloak signing-key rotation without waiting for JWKS cache TTL.
                jwks = await _get_keycloak_jwks(force_refresh=True)
                key = _jwk_signing_key(jwks, kid)
            if key is None:
                raise HTTPException(status_code=401, detail="Invalid token key")

            return jwt.decode(
                raw_token,
                key,
                algorithms=[alg],
                audience=audience,
                options={"verify_iss": False},
            )

        payload = await _decode_token(token, settings.keycloak_audience)
        token_issuer = str(payload.get("iss") or "").rstrip("/")
        if token_issuer not in _allowed_issuers(settings):
            raise HTTPException(status_code=401, detail="Invalid token issuer")

        # Some Keycloak setups issue access tokens without `sub` for this client profile.
        # In cookie-auth flow we can safely recover subject/email from OIDC id_token.
        id_payload: dict[str, Any] | None = None
        userinfo_payload: dict[str, Any] | None = None

        async def _ensure_userinfo() -> dict[str, Any] | None:
            nonlocal userinfo_payload
            if userinfo_payload is None:
                userinfo_payload = await _fetch_userinfo(token)
            return userinfo_payload

        sub = payload.get("sub")
        if not sub and not credentials:
            id_token = request.cookies.get("id_token")
            if id_token:
                try:
                    id_payload = await _decode_token(id_token, settings.oidc_frontend_client_id)
                    id_issuer = str(id_payload.get("iss") or "").rstrip("/")
                    if id_issuer not in _allowed_issuers(settings):
                        id_payload = None
                except Exception:
                    id_payload = None
            if id_payload:
                sub = id_payload.get("sub")
            if not sub:
                userinfo = await _ensure_userinfo()
                if userinfo:
                    sub = userinfo.get("sub")

        if not sub:
            logger.warning("Missing token subject claim after access/id/userinfo fallback")
            raise HTTPException(status_code=401, detail="Missing token subject")
        tenant_id_raw = payload.get("tenant_id")
        if not tenant_id_raw and id_payload is not None:
            tenant_id_raw = id_payload.get("tenant_id")
        if not tenant_id_raw:
            userinfo = await _ensure_userinfo()
            if userinfo is not None:
                userinfo_sub = userinfo.get("sub")
                if userinfo_sub and str(userinfo_sub) != str(sub):
                    raise HTTPException(status_code=401, detail="Userinfo subject mismatch")
                tenant_id_raw = userinfo.get("tenant_id")
        try:
            tenant_id = str(uuid.UUID(str(tenant_id_raw)))
        except Exception:
            raise HTTPException(status_code=403, detail="Missing or invalid tenant claim")
        email = str(payload.get("email") or payload.get("preferred_username") or "")
        if not email and id_payload is not None:
            email = str(id_payload.get("email") or id_payload.get("preferred_username") or "")
        if not email:
            userinfo = await _ensure_userinfo()
            if userinfo is not None:
                userinfo_sub = userinfo.get("sub")
                if userinfo_sub and str(userinfo_sub) != str(sub):
                    raise HTTPException(status_code=401, detail="Userinfo subject mismatch")
                email = str(userinfo.get("email") or userinfo.get("preferred_username") or "")
        if not email:
            email = _fallback_identity_email(str(sub))

        role: str
        try:
            role = _extract_role(payload)
        except HTTPException:
            role = ""
            if id_payload is not None:
                try:
                    role = _extract_role(id_payload)
                except HTTPException:
                    role = ""
            if not role:
                userinfo = await _ensure_userinfo()
                if userinfo is not None:
                    try:
                        role = _extract_role(userinfo)
                    except HTTPException:
                        role = ""
            if not role:
                raise

        return AuthContext(
            user_id=str(sub),
            tenant_id=tenant_id,
            email=email,
            role=role,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Token validation failed: %s: %s", exc.__class__.__name__, str(exc)[:300])
        raise HTTPException(status_code=401, detail="Token validation failed") from exc


def require_admin(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return ctx
