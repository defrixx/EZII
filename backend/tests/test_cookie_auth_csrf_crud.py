from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.core.security import AuthContext, require_admin
from app.main import app


def _dummy_db():
    class DummyDb:
        def commit(self):
            return None

        def rollback(self):
            return None

        def refresh(self, row):
            return row

    return DummyDb()


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


def test_chat_create_rejects_cookie_auth_without_origin_and_csrf():
    from app.api.v1 import chats as chats_module

    app.dependency_overrides[chats_module.auth_dep] = _user_ctx
    app.dependency_overrides[db_dep] = _dummy_db
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/chats",
            json={"title": "New chat"},
            cookies={"access_token": "dummy-cookie-auth"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_glossary_create_rejects_cookie_auth_without_origin_and_csrf():
    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = _dummy_db
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/glossary",
            json={"name": "Ops", "description": "desc", "priority": 100, "enabled": True},
            cookies={"access_token": "dummy-cookie-auth"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_admin_provider_update_rejects_cookie_auth_without_origin_and_csrf():
    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = _dummy_db
    client = TestClient(app)
    try:
        response = client.put(
            "/api/v1/admin/provider",
            json={
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "x" * 24,
                "model_name": "openai/gpt-4o-mini",
                "embedding_model": "text-embedding-3-small",
                "timeout_s": 30,
                "retry_policy": 2,
                "knowledge_mode": "glossary_documents",
                "empty_retrieval_mode": "model_only_fallback",
                "strict_glossary_mode": False,
                "show_confidence": False,
                "show_source_tags": True,
                "response_tone": "consultative_supportive",
                "max_user_messages_total": 5,
                "chat_context_enabled": True,
                "history_user_turn_limit": 6,
                "history_message_limit": 12,
                "history_token_budget": 1200,
                "rewrite_history_message_limit": 8,
            },
            cookies={"access_token": "dummy-cookie-auth"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
