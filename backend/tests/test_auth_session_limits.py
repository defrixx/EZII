from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.v1 import auth as auth_module
from app.core.security import AuthContext


def _user_ctx() -> AuthContext:
    return AuthContext(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="22222222-2222-2222-2222-222222222222",
        email="user@example.com",
        role="user",
    )


def _admin_ctx() -> AuthContext:
    return AuthContext(
        user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        email="admin@example.com",
        role="admin",
    )


class _FakeDb:
    def __init__(self, provider_settings, used_today: int = 0):
        self.provider_settings = provider_settings
        self.used_today = used_today
        self.scalar_calls = 0

    def scalar(self, _stmt):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.provider_settings
        return self.used_today


def test_session_info_returns_user_daily_limit_payload(monkeypatch):
    provider_settings = SimpleNamespace(
        show_source_tags=True,
        max_user_messages_total=5,
    )
    db = _FakeDb(provider_settings, used_today=5)
    fixed_start = datetime(2026, 3, 31, 0, 0, 0, tzinfo=UTC)
    fixed_reset = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(auth_module, "ensure_user_exists", lambda _db, _ctx: None)
    monkeypatch.setattr(auth_module, "limit_window_start_utc", lambda *_args, **_kwargs: fixed_start)
    monkeypatch.setattr(auth_module, "limit_window_reset_at_utc", lambda *_args, **_kwargs: fixed_reset)

    payload = auth_module.session_info(_user_ctx(), db)

    assert payload["role"] == "user"
    assert payload["show_source_tags"] is True
    assert payload["message_limit_total"] == 5
    assert payload["message_limit_used_today"] == 5
    assert payload["message_limit_remaining_today"] == 0
    assert payload["message_limit_resets_at"] == "2026-04-01T00:00:00Z"
    assert db.scalar_calls == 2


def test_session_info_for_admin_exposes_no_remaining_quota(monkeypatch):
    provider_settings = SimpleNamespace(
        show_source_tags=False,
        max_user_messages_total=99,
    )
    db = _FakeDb(provider_settings, used_today=42)
    fixed_start = datetime(2026, 3, 31, 0, 0, 0, tzinfo=UTC)
    fixed_reset = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(auth_module, "ensure_user_exists", lambda _db, _ctx: None)
    monkeypatch.setattr(auth_module, "limit_window_start_utc", lambda *_args, **_kwargs: fixed_start)
    monkeypatch.setattr(auth_module, "limit_window_reset_at_utc", lambda *_args, **_kwargs: fixed_reset)

    payload = auth_module.session_info(_admin_ctx(), db)

    assert payload["role"] == "admin"
    assert payload["show_source_tags"] is False
    assert payload["message_limit_total"] == 99
    assert payload["message_limit_used_today"] == 0
    assert payload["message_limit_remaining_today"] is None
    assert payload["message_limit_resets_at"] == "2026-04-01T00:00:00Z"
    assert db.scalar_calls == 1
