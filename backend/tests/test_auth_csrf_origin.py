from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app

client = TestClient(app)


def _post_with_cookies(path: str, *, headers: dict | None = None, cookies: dict | None = None):
    client.cookies.clear()
    for key, value in (cookies or {}).items():
        client.cookies.set(key, value)
    return client.post(path, headers=headers)


def test_refresh_rejects_missing_origin_referer():
    cookies = {"refresh_token": "dummy", "csrf_token": "abc"}
    headers = {"x-csrf-token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "Origin/Referer" in r.text


def test_refresh_rejects_bad_csrf_even_with_origin():
    cookies = {"refresh_token": "dummy", "csrf_token": "abc"}
    headers = {"x-csrf-token": "wrong", "origin": "http://localhost"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "CSRF" in r.text


def test_refresh_rejects_missing_csrf_cookie():
    headers = {"x-csrf-token": "abc", "origin": "http://localhost"}
    cookies = {"refresh_token": "dummy"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "CSRF" in r.text


def test_refresh_rejects_missing_csrf_header():
    headers = {"origin": "http://localhost"}
    cookies = {"refresh_token": "dummy", "csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "CSRF" in r.text


def test_refresh_rejects_untrusted_origin():
    headers = {"x-csrf-token": "abc", "origin": "https://evil.example.com"}
    cookies = {"refresh_token": "dummy", "csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "Untrusted Origin" in r.text


def test_refresh_rejects_untrusted_referer():
    headers = {"x-csrf-token": "abc", "referer": "https://evil.example.com/path"}
    cookies = {"refresh_token": "dummy", "csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "Untrusted Referer" in r.text


def test_logout_rejects_without_csrf_or_origin():
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 403


def test_logout_rejects_untrusted_origin():
    headers = {"x-csrf-token": "abc", "origin": "https://evil.example.com"}
    cookies = {"csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/logout", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "Untrusted Origin" in r.text


def test_logout_accepts_trusted_referer_and_clears_cookies():
    headers = {"x-csrf-token": "abc", "referer": "http://localhost/logout"}
    cookies = {"csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/logout", headers=headers, cookies=cookies)
    assert r.status_code == 200
    set_cookie = ", ".join(r.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
    assert "id_token=" in set_cookie


def test_logout_clears_cookies_even_when_revoke_fails(monkeypatch):
    from app.api.v1 import auth as auth_module

    async def _revoke_tokens(refresh_token: str | None, access_token: str | None) -> None:
        raise HTTPException(status_code=502, detail="revoke failed")

    monkeypatch.setattr(auth_module, "_revoke_tokens", _revoke_tokens)

    headers = {"x-csrf-token": "abc", "origin": "http://localhost"}
    cookies = {"csrf_token": "abc", "access_token": "access", "refresh_token": "refresh"}
    r = _post_with_cookies("/api/v1/auth/logout", headers=headers, cookies=cookies)
    assert r.status_code == 502
    set_cookie = ", ".join(r.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie


def test_refresh_missing_refresh_token_clears_auth_cookies():
    headers = {"x-csrf-token": "abc", "origin": "http://localhost"}
    cookies = {"csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 401
    set_cookie = ", ".join(r.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie


def test_refresh_accepts_trusted_referer_without_origin():
    headers = {"x-csrf-token": "abc", "referer": "http://localhost/auth/refresh"}
    cookies = {"csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 401
    assert "Missing refresh token" in r.text


def test_refresh_accepts_same_origin_from_host_header(monkeypatch):
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module, "TRUSTED_ORIGINS", set())
    headers = {"x-csrf-token": "abc", "host": "localhost"}
    cookies = {"csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 401
    assert "Missing refresh token" in r.text


def test_refresh_accepts_same_host_even_when_origin_scheme_differs(monkeypatch):
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module, "TRUSTED_ORIGINS", set())
    headers = {"x-csrf-token": "abc", "origin": "https://localhost", "host": "localhost"}
    cookies = {"csrf_token": "abc"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 401
    assert "Missing refresh token" in r.text


def test_refresh_accepts_valid_origin_and_csrf(monkeypatch):
    from app.api.v1 import auth as auth_module

    class DummyResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "id_token": "new-id",
                "expires_in": 300,
            }

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data=None):
            return DummyResponse()

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda timeout=15: DummyClient())

    headers = {"x-csrf-token": "abc", "origin": "http://localhost"}
    cookies = {"csrf_token": "abc", "refresh_token": "refresh"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 200
    set_cookie = ", ".join(r.headers.get_list("set-cookie"))
    assert "access_token=new-access" in set_cookie
    assert "refresh_token=new-refresh" in set_cookie


def test_refresh_rejects_empty_access_token_and_clears_auth_cookies(monkeypatch):
    from app.api.v1 import auth as auth_module

    class DummyResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "access_token": "   ",
                "refresh_token": "new-refresh",
                "id_token": "new-id",
                "expires_in": 300,
            }

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data=None):
            return DummyResponse()

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda timeout=15: DummyClient())

    headers = {"x-csrf-token": "abc", "origin": "http://localhost"}
    cookies = {"csrf_token": "abc", "refresh_token": "refresh"}
    r = _post_with_cookies("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 401
    assert "empty access token" in r.text
    set_cookie = ", ".join(r.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
