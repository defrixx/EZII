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


def _issuer() -> str:
    settings = security.get_settings()
    return f"{settings.keycloak_issuer.rstrip('/')}/realms/{settings.keycloak_realm}"


def test_auth_context_rejects_invalid_tenant_uuid(monkeypatch):
    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {
            "sub": "user-1",
            "tenant_id": "not-a-uuid",
            "email": "u@example.com",
            "realm_access": {"roles": ["user"]},
            "iss": _issuer(),
        },
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
        lambda *args, **kwargs: {
            "sub": "user-1",
            "tenant_id": tenant_id,
            "email": "u@example.com",
            "realm_access": {"roles": ["user"]},
            "iss": _issuer(),
        },
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    out = asyncio.run(security.get_auth_context(req, creds))
    assert out.tenant_id == tenant_id


def test_auth_context_rejects_missing_business_role(monkeypatch):
    tenant_id = "00000000-0000-0000-0000-000000000001"

    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {
            "sub": "user-1",
            "tenant_id": tenant_id,
            "email": "u@example.com",
            "realm_access": {"roles": ["service-account"]},
            "iss": _issuer(),
        },
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    try:
        asyncio.run(security.get_auth_context(req, creds))
        assert False, "Expected missing role to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_auth_context_ignores_client_roles_for_business_role(monkeypatch):
    tenant_id = "00000000-0000-0000-0000-000000000001"

    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {
            "sub": "user-1",
            "tenant_id": tenant_id,
            "email": "u@example.com",
            "realm_access": {"roles": ["offline_access"]},
            "resource_access": {"some-other-client": {"roles": ["admin"]}},
            "iss": _issuer(),
        },
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    try:
        asyncio.run(security.get_auth_context(req, creds))
        assert False, "Expected client roles to be ignored for authorization"
    except HTTPException as exc:
        assert exc.status_code == 403


def test_auth_context_retries_jwks_fetch_when_kid_not_in_cache(monkeypatch):
    tenant_id = "00000000-0000-0000-0000-000000000001"
    calls = {"force": []}

    async def _jwks(force_refresh: bool = False):
        calls["force"].append(force_refresh)
        if force_refresh:
            return {"keys": [{"kid": "new-kid"}]}
        return {"keys": [{"kid": "old-kid"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "new-kid"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {
            "sub": "user-1",
            "tenant_id": tenant_id,
            "email": "u@example.com",
            "realm_access": {"roles": ["user"]},
            "iss": _issuer(),
        },
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    out = asyncio.run(security.get_auth_context(req, creds))
    assert out.tenant_id == tenant_id
    assert calls["force"] == [False, True]


def test_auth_context_accepts_ps256_access_token_alg(monkeypatch):
    tenant_id = "00000000-0000-0000-0000-000000000001"

    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1", "alg": "PS256"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {
            "sub": "user-1",
            "tenant_id": tenant_id,
            "email": "u@example.com",
            "realm_access": {"roles": ["user"]},
            "iss": _issuer(),
        },
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    out = asyncio.run(security.get_auth_context(req, creds))
    assert out.tenant_id == tenant_id


def test_auth_context_rejects_disallowed_token_alg(monkeypatch):
    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1", "alg": "HS256"})

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    try:
        asyncio.run(security.get_auth_context(req, creds))
        assert False, "Expected unsupported token algorithm to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "algorithm" in str(exc.detail).lower()


def test_auth_context_rejects_missing_sub_claim(monkeypatch):
    tenant_id = "00000000-0000-0000-0000-000000000001"

    async def _jwks():
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(security, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(security.jwt, "get_unverified_header", lambda token: {"kid": "k1"})
    monkeypatch.setattr(
        security.jwt,
        "decode",
        lambda *args, **kwargs: {
            "tenant_id": tenant_id,
            "email": "u@example.com",
            "realm_access": {"roles": ["user"]},
            "iss": _issuer(),
        },
    )

    req = _make_request()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    try:
        asyncio.run(security.get_auth_context(req, creds))
        assert False, "Expected missing token subject to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "subject" in str(exc.detail).lower()
