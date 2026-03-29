from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.core.security import AuthContext
from app.main import app


def _user_ctx() -> AuthContext:
    return AuthContext(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="22222222-2222-2222-2222-222222222222",
        email="user@example.com",
        role="user",
    )


def test_list_chats_supports_include_archived(monkeypatch):
    from app.api.v1 import chats as chats_module

    captured: dict[str, bool] = {}

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

        def list_chats(self, tenant_id: str, user_id: str, *, include_archived: bool = False):
            captured["include_archived"] = include_archived
            return [
                SimpleNamespace(
                    id="chat-1",
                    title="Pinned chat",
                    is_pinned=True,
                    is_archived=False,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]

    app.dependency_overrides[chats_module.auth_dep] = _user_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(chats_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(chats_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(chats_module, "check_rate_limit", lambda request, tenant_id, user_id: None)

    client = TestClient(app)
    try:
        response = client.get("/api/v1/chats?include_archived=true")
        assert response.status_code == 200
        assert captured["include_archived"] is True
        payload = response.json()
        assert payload[0]["is_pinned"] is True
        assert payload[0]["is_archived"] is False
    finally:
        app.dependency_overrides.clear()


def test_update_chat_supports_pin_and_archive(monkeypatch):
    from app.api.v1 import chats as chats_module

    captured: dict[str, object] = {}

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

        def update_chat(self, tenant_id: str, user_id: str, chat_id: str, *, title=None, is_pinned=None, is_archived=None):
            captured["title"] = title
            captured["is_pinned"] = is_pinned
            captured["is_archived"] = is_archived
            return SimpleNamespace(
                id=chat_id,
                title=title or "Updated",
                is_pinned=bool(is_pinned),
                is_archived=bool(is_archived),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    app.dependency_overrides[chats_module.auth_dep] = _user_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(chats_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(chats_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(chats_module, "check_rate_limit", lambda request, tenant_id, user_id: None)

    client = TestClient(app)
    try:
        response = client.patch(
            "/api/v1/chats/11111111-1111-1111-1111-111111111112",
            json={"is_pinned": True, "is_archived": False},
        )
        assert response.status_code == 200
        assert captured["is_pinned"] is True
        assert captured["is_archived"] is False
        payload = response.json()
        assert payload["is_pinned"] is True
        assert payload["is_archived"] is False
    finally:
        app.dependency_overrides.clear()


def test_update_chat_rejects_empty_payload(monkeypatch):
    from app.api.v1 import chats as chats_module

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

    app.dependency_overrides[chats_module.auth_dep] = _user_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(chats_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(chats_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(chats_module, "check_rate_limit", lambda request, tenant_id, user_id: None)

    client = TestClient(app)
    try:
        response = client.patch(
            "/api/v1/chats/11111111-1111-1111-1111-111111111112",
            json={},
        )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()

