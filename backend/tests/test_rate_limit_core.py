import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import rate_limit as rate_limit_module


class FakeRedis:
    def __init__(self, values: dict[str, int] | None = None, fail: bool = False):
        self.values = values or {}
        self.fail = fail
        self.expire_calls: list[tuple[str, int]] = []

    def incr(self, key: str) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.expire_calls.append((key, seconds))


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }
    )


def test_check_rate_limit_allows_first_request_and_sets_ttl(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(rate_limit_module, "_redis", fake_redis)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_per_minute", 3)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_fail_open", False)
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: 120.0)

    rate_limit_module.check_rate_limit(_request(), tenant_id="t-1", user_id="u-1")

    assert fake_redis.expire_calls == [("rl:t-1:u-1:2", 70)]


def test_check_rate_limit_returns_429_when_limit_exceeded(monkeypatch):
    fake_redis = FakeRedis({"rl:t-1:u-1:2": 2})
    monkeypatch.setattr(rate_limit_module, "_redis", fake_redis)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_per_minute", 2)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_fail_open", False)
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: 120.0)

    with pytest.raises(HTTPException) as exc:
        rate_limit_module.check_rate_limit(_request(), tenant_id="t-1", user_id="u-1")
    assert exc.value.status_code == 429
    assert "rate limit exceeded" in str(exc.value.detail).lower()


def test_check_rate_limit_fail_closed_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "_redis", FakeRedis(fail=True))
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_fail_open", False)

    with pytest.raises(HTTPException) as exc:
        rate_limit_module.check_rate_limit(_request(), tenant_id="t-1", user_id="u-1")
    assert exc.value.status_code == 503
    assert "unavailable" in str(exc.value.detail).lower()


def test_check_rate_limit_fail_open_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "_redis", FakeRedis(fail=True))
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_fail_open", True)

    rate_limit_module.check_rate_limit(_request(), tenant_id="t-1", user_id="u-1")


def test_registration_rate_limit_blocks_email_and_sets_hourly_ttl(monkeypatch):
    fake_redis = FakeRedis({"rl:register:ip:127.0.0.1:1": 0, "rl:register:email:a@b.test:1": 1})
    monkeypatch.setattr(rate_limit_module, "_redis", fake_redis)
    monkeypatch.setattr(rate_limit_module.settings, "register_rate_limit_per_ip_per_hour", 10)
    monkeypatch.setattr(rate_limit_module.settings, "register_rate_limit_per_email_per_hour", 1)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_fail_open", False)
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: 3600.0)

    with pytest.raises(HTTPException) as exc:
        rate_limit_module.check_registration_rate_limit(_request(), email="a@b.test")

    assert exc.value.status_code == 429
    assert "email" in str(exc.value.detail).lower()
    assert ("rl:register:ip:127.0.0.1:1", 3700) in fake_redis.expire_calls


def test_registration_captcha_rate_limit_blocks_ip_when_exceeded(monkeypatch):
    fake_redis = FakeRedis({"rl:register:captcha:ip:127.0.0.1:1": 1})
    monkeypatch.setattr(rate_limit_module, "_redis", fake_redis)
    monkeypatch.setattr(rate_limit_module.settings, "register_captcha_rate_limit_per_ip_per_hour", 1)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_fail_open", False)
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: 3600.0)

    with pytest.raises(HTTPException) as exc:
        rate_limit_module.check_registration_captcha_rate_limit(_request())
    assert exc.value.status_code == 429
    assert "captcha" in str(exc.value.detail).lower()
