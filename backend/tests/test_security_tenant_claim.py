import asyncio

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app.core import security


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_auth_context_rejects_invalid_tenant_uuid(monkeypatch):
    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {"sub": "user-1", "tenant_id": "not-a-uuid", "email": "u@example.com"},
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    try:
        asyncio.run(security.get_auth_context(req, creds))
        assert False, "Expected invalid tenant claim to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_auth_context_accepts_valid_tenant_uuid(monkeypatch):
    tenant_id = "00000000-0000-0000-0000-000000000001"

    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {"sub": "user-1", "tenant_id": tenant_id, "email": "u@example.com"},
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    out = asyncio.run(security.get_auth_context(req, creds))
    assert out.tenant_id == tenant_id
