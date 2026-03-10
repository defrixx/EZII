import asyncio

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.main import app


def _issuer(auth_module) -> str:
    return f"{auth_module.settings.keycloak_issuer.rstrip('/')}/realms/{auth_module.settings.keycloak_realm}"


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
    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {
            "nonce": "other",
            "aud": auth_module.settings.oidc_frontend_client_id,
            "iss": _issuer(auth_module),
        },
    )

    try:
        asyncio.run(auth_module._validate_nonce("token", "expected"))
        assert False, "Expected nonce mismatch to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "nonce" in str(exc.detail).lower()


def test_validate_nonce_accepts_azp_when_aud_is_not_string(monkeypatch):
    from app.api.v1 import auth as auth_module

    async def _jwks():
        return {"keys": [{"kid": "kid-1"}]}

    monkeypatch.setattr(auth_module, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {
            "nonce": "expected",
            "aud": ["account"],
            "azp": auth_module.settings.oidc_frontend_client_id,
            "iss": _issuer(auth_module),
        },
    )

    asyncio.run(auth_module._validate_nonce("token", "expected"))


def test_validate_nonce_retries_jwks_when_kid_rotated(monkeypatch):
    from app.api.v1 import auth as auth_module

    calls = {"force": []}

    async def _jwks(force_refresh: bool = False):
        calls["force"].append(force_refresh)
        if force_refresh:
            return {"keys": [{"kid": "kid-2"}]}
        return {"keys": [{"kid": "kid-1"}]}

    monkeypatch.setattr(auth_module, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-2"})
    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {
            "nonce": "expected",
            "aud": auth_module.settings.oidc_frontend_client_id,
            "iss": _issuer(auth_module),
        },
    )

    asyncio.run(auth_module._validate_nonce("token", "expected"))
    assert calls["force"] == [False, True]


def test_validate_nonce_accepts_ps256_header_alg(monkeypatch):
    from app.api.v1 import auth as auth_module

    async def _jwks(force_refresh: bool = False):
        return {"keys": [{"kid": "kid-1"}]}

    monkeypatch.setattr(auth_module, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1", "alg": "PS256"})
    monkeypatch.setattr(
        auth_module.jwt,
        "decode",
        lambda *args, **kwargs: {
            "nonce": "expected",
            "aud": auth_module.settings.oidc_frontend_client_id,
            "iss": _issuer(auth_module),
        },
    )

    asyncio.run(auth_module._validate_nonce("token", "expected"))


def test_validate_nonce_retries_decode_after_forced_jwks_refresh(monkeypatch):
    from app.api.v1 import auth as auth_module

    calls = {"jwks": [], "decode": 0}

    async def _jwks(force_refresh: bool = False):
        calls["jwks"].append(force_refresh)
        return {"keys": [{"kid": "kid-1"}]}

    def _decode(*args, **kwargs):
        calls["decode"] += 1
        if calls["decode"] == 1:
            raise RuntimeError("signature mismatch")
        return {
            "nonce": "expected",
            "aud": auth_module.settings.oidc_frontend_client_id,
            "iss": _issuer(auth_module),
        }

    monkeypatch.setattr(auth_module, "_get_keycloak_jwks", _jwks)
    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1", "alg": "RS256"})
    monkeypatch.setattr(auth_module.jwt, "decode", _decode)

    asyncio.run(auth_module._validate_nonce("token", "expected"))
    assert calls["decode"] == 2
    assert calls["jwks"] == [False, True]


def test_validate_nonce_rejects_disallowed_algorithm(monkeypatch):
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module.jwt, "get_unverified_header", lambda token: {"kid": "kid-1", "alg": "HS256"})

    try:
        asyncio.run(auth_module._validate_nonce("token", "nonce"))
        assert False, "Expected disallowed algorithm to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert "algorithm" in str(exc.detail).lower()


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


def test_create_keycloak_user_marks_email_verified_when_email_verification_disabled(monkeypatch):
    from app.api.v1 import auth as auth_module

    captured_payload: dict = {}

    class DummyResponse:
        def __init__(self, status_code: int, body=None):
            self.status_code = status_code
            self._body = body if body is not None else {}
            self.text = ""

        def json(self):
            return self._body

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None, params=None, data=None):
            if url.endswith("/users"):
                captured_payload.update(json or {})
                return DummyResponse(201, {})
            if url.endswith("/role-mappings/realm"):
                return DummyResponse(204, {})
            return DummyResponse(204, {})

        async def get(self, url, headers=None, params=None):
            if url.endswith("/users"):
                return DummyResponse(200, [{"id": "user-1"}])
            if url.endswith("/roles/user"):
                return DummyResponse(200, {"id": "role-user", "name": "user"})
            if url.endswith("/roles/admin"):
                return DummyResponse(404, {})
            return DummyResponse(404, {})

        async def delete(self, url, headers=None, json=None):
            return DummyResponse(204, {})

        async def put(self, url, headers=None, params=None, json=None):
            return DummyResponse(204, {})

    async def _admin_token():
        return "admin-token"

    monkeypatch.setattr(auth_module.settings, "register_require_email_verification", False)
    monkeypatch.setattr(auth_module.settings, "register_requires_admin_approval", False)
    monkeypatch.setattr(auth_module, "_keycloak_admin_token", _admin_token)
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda timeout=20: DummyClient())

    out = asyncio.run(
        auth_module._create_keycloak_user(
            email="user@example.com",
            password="StrongPass123!",
            tenant_id="00000000-0000-0000-0000-000000000001",
        )
    )
    assert out is True
    assert captured_payload.get("emailVerified") is True
    assert captured_payload.get("requiredActions") == []
