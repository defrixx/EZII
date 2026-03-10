import asyncio

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.main import app


def test_oidc_exchange_rejects_untrusted_redirect_uri():
    client = TestClient(app)
    payload = {
        "code": "dummy",
        "code_verifier": "verifier",
        "nonce": "nonce",
        "redirect_uri": "https://evil.example.com/callback",
    }
    r = client.post("/api/v1/auth/oidc/exchange", json=payload)
    assert r.status_code == 400
    assert "redirect_uri" in r.text


def test_validate_nonce_rejects_invalid_id_token_signature(monkeypatch):
    from app.api.v1 import auth as auth_module

    async def _jwks():
        return {"keys": [{"kid": "kid-1"}]}

    monkeypatch.setattr(auth_module, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})

    def _raise_decode(*args, **kwargs):
        raise RuntimeError("bad signature")

    monkeypatch.setattr(auth_module.jwt, "decode", _raise_decode)

    try:
        asyncio.run(auth_module._validate_nonce("token", "nonce"))
        assert False, "Expected invalid id_token to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "id_token" in str(exc.detail)


def test_validate_nonce_rejects_nonce_mismatch_after_verified_decode(monkeypatch):
    from app.api.v1 import auth as auth_module

    async def _jwks():
        return {"keys": [{"kid": "kid-1"}]}

    monkeypatch.setattr(auth_module, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(auth_module.jwt, "decode", lambda *args, **kwargs: {"nonce": "other"})

    try:
        asyncio.run(auth_module._validate_nonce("token", "expected"))
        assert False, "Expected nonce mismatch to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "nonce" in str(exc.detail).lower()


def test_register_uses_neutral_response(monkeypatch):
    from app.api.v1 import auth as auth_module

    async def _create_keycloak_user(email: str, password: str, tenant_id: str) -> bool:
        return False

    monkeypatch.setattr(auth_module.settings, "register_enforce_captcha", False)
    monkeypatch.setattr(auth_module, "check_registration_rate_limit", lambda request, email: None)
    monkeypatch.setattr(auth_module, "_resolve_registration_tenant", lambda db: "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(auth_module, "_create_keycloak_user", _create_keycloak_user)

    app.dependency_overrides[db_dep] = lambda: object()
    client = TestClient(app)
    try:
        r = client.post(
            "/api/v1/auth/register",
            headers={"origin": "http://localhost"},
            json={"email": "user@example.com", "password": "StrongPass123!"},
        )
        assert r.status_code == 202
        assert r.json().get("detail") == auth_module.REGISTER_NEUTRAL_DETAIL
    finally:
        app.dependency_overrides.clear()
