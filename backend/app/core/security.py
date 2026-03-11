import logging
import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
import httpx
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


@dataclass
class AuthContext:
    user_id: str
    tenant_id: str
    email: str
    role: str


def _extract_role(payload: dict[str, Any]) -> str:
    roles = payload.get("realm_access", {}).get("roles", [])
    if not isinstance(roles, list):
        roles = []
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
            key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
            if not key and kid and allow_force_refresh:
                # Handle Keycloak signing-key rotation without waiting for JWKS cache TTL.
                jwks = await _get_keycloak_jwks(force_refresh=True)
                key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
            if not key:
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
            raise HTTPException(status_code=401, detail="Missing token subject")
        tenant_id_raw = payload.get("tenant_id")
        if not tenant_id_raw and id_payload is not None:
            tenant_id_raw = id_payload.get("tenant_id")
        try:
            tenant_id = str(uuid.UUID(str(tenant_id_raw)))
        except Exception:
            raise HTTPException(status_code=403, detail="Missing or invalid tenant claim")
        email = str(payload.get("email") or payload.get("preferred_username") or "")
        if not email and id_payload is not None:
            email = str(id_payload.get("email") or id_payload.get("preferred_username") or "")
        return AuthContext(
            user_id=str(sub),
            tenant_id=tenant_id,
            email=email,
            role=_extract_role(payload),
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
