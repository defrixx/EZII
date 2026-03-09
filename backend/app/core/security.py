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


@dataclass
class AuthContext:
    user_id: str
    tenant_id: str
    email: str
    role: str


def _extract_role(payload: dict[str, Any]) -> str:
    roles = payload.get("realm_access", {}).get("roles", [])
    if "admin" in roles:
        return "admin"
    return "user"


async def _get_keycloak_jwks() -> dict:
    global _jwks_cache, _jwks_cache_expire_at
    settings = get_settings()
    now = time.monotonic()
    if _jwks_cache and now < _jwks_cache_expire_at:
        return _jwks_cache

    url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"
    async with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache and now < _jwks_cache_expire_at:
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
        unverified_header = jwt.get_unverified_header(token)
        jwks = await _get_keycloak_jwks()
        key = next((k for k in jwks["keys"] if k["kid"] == unverified_header["kid"]), None)
        if not key:
            raise HTTPException(status_code=401, detail="Invalid token key")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.keycloak_audience,
            issuer=f"{settings.keycloak_issuer.rstrip('/')}/realms/{settings.keycloak_realm}",
        )
        tenant_id_raw = payload.get("tenant_id")
        try:
            tenant_id = str(uuid.UUID(str(tenant_id_raw)))
        except Exception:
            raise HTTPException(status_code=403, detail="Missing or invalid tenant claim")
        return AuthContext(
            user_id=payload["sub"],
            tenant_id=tenant_id,
            email=payload.get("email", ""),
            role=_extract_role(payload),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Token validation failed: %s", exc.__class__.__name__)
        raise HTTPException(status_code=401, detail="Token validation failed") from exc


def require_admin(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return ctx
