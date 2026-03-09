import asyncio
import time

from app.core import security


def _reset_jwks_cache():
    security._jwks_cache = None
    security._jwks_cache_expire_at = 0.0


def test_get_keycloak_jwks_uses_fresh_cache_without_http(monkeypatch):
    _reset_jwks_cache()
    cached = {"keys": [{"kid": "k1"}]}
    security._jwks_cache = cached
    security._jwks_cache_expire_at = time.monotonic() + 60

    class FailIfCalledClient:
        async def __aenter__(self):
            raise AssertionError("HTTP client should not be called for fresh cache")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(security.httpx, "AsyncClient", lambda timeout=10: FailIfCalledClient())
    out = asyncio.run(security._get_keycloak_jwks())
    assert out == cached


def test_get_keycloak_jwks_falls_back_to_stale_cache_on_fetch_error(monkeypatch):
    _reset_jwks_cache()
    stale = {"keys": [{"kid": "stale"}]}
    security._jwks_cache = stale
    security._jwks_cache_expire_at = time.monotonic() - 1

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            raise RuntimeError("network down")

    monkeypatch.setattr(security.httpx, "AsyncClient", lambda timeout=10: FailingClient())
    out = asyncio.run(security._get_keycloak_jwks())
    assert out == stale


def test_get_keycloak_jwks_updates_cache_after_success(monkeypatch):
    _reset_jwks_cache()
    fresh = {"keys": [{"kid": "new"}]}
    calls = {"count": 0}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return fresh

    class SuccessClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            calls["count"] += 1
            return DummyResponse()

    monkeypatch.setattr(security.httpx, "AsyncClient", lambda timeout=10: SuccessClient())

    out1 = asyncio.run(security._get_keycloak_jwks())
    out2 = asyncio.run(security._get_keycloak_jwks())

    assert out1 == fresh
    assert out2 == fresh
    assert calls["count"] == 1

