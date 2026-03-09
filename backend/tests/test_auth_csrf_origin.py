from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_refresh_rejects_missing_origin_referer():
    cookies = {"refresh_token": "dummy", "csrf_token": "abc"}
    headers = {"x-csrf-token": "abc"}
    r = client.post("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "Origin/Referer" in r.text


def test_refresh_rejects_bad_csrf_even_with_origin():
    cookies = {"refresh_token": "dummy", "csrf_token": "abc"}
    headers = {"x-csrf-token": "wrong", "origin": "http://localhost"}
    r = client.post("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 403
    assert "CSRF" in r.text


def test_logout_rejects_without_csrf_or_origin():
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 403


def test_refresh_missing_refresh_token_clears_auth_cookies():
    headers = {"x-csrf-token": "abc", "origin": "http://localhost"}
    cookies = {"csrf_token": "abc"}
    r = client.post("/api/v1/auth/oidc/refresh", headers=headers, cookies=cookies)
    assert r.status_code == 401
    set_cookie = ", ".join(r.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookie
    assert "refresh_token=" in set_cookie
