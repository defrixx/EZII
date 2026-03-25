from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.core.security import AuthContext, require_admin
from app.main import app


def _admin_ctx() -> AuthContext:
    return AuthContext(
        user_id="00000000-0000-0000-0000-0000000000aa",
        tenant_id="00000000-0000-0000-0000-0000000000bb",
        email="admin@example.com",
        role="admin",
    )


def test_put_provider_persists_conversational_context_settings(monkeypatch):
    from app.api.v1 import admin as admin_module

    captured: dict = {}

    async def _verify_embedding_dimension(**kwargs):
        return None

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return None

        def upsert_provider(self, tenant_id: str, payload: dict):
            captured["tenant_id"] = tenant_id
            captured["payload"] = payload
            return SimpleNamespace(
                id="provider-1",
                tenant_id=tenant_id,
                base_url=payload["base_url"],
                api_key=payload["api_key"],
                model_name=payload["model_name"],
                embedding_model=payload["embedding_model"],
                timeout_s=payload["timeout_s"],
                retry_policy=payload["retry_policy"],
                knowledge_mode=payload["knowledge_mode"],
                empty_retrieval_mode=payload["empty_retrieval_mode"],
                strict_glossary_mode=payload["strict_glossary_mode"],
                show_confidence=payload["show_confidence"],
                show_source_tags=payload["show_source_tags"],
                response_tone=payload["response_tone"],
                max_user_messages_total=payload["max_user_messages_total"],
                chat_context_enabled=payload["chat_context_enabled"],
                history_user_turn_limit=payload["history_user_turn_limit"],
                history_message_limit=payload["history_message_limit"],
                history_token_budget=payload["history_token_budget"],
                rewrite_history_message_limit=payload["rewrite_history_message_limit"],
                updated_at=datetime.now(UTC),
            )

        def add_audit_log(self, *args, **kwargs):
            return None

        @staticmethod
        def provider_api_key_plain(row):
            return "sk-test-provider-key-123456"

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module, "_verify_embedding_dimension", _verify_embedding_dimension)
    monkeypatch.setattr(admin_module, "_validate_provider_base_url_public_sync", lambda base_url: None)

    client = TestClient(app)
    try:
        response = client.put(
            "/api/v1/admin/provider",
            json={
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-test-provider-key-123456",
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
                "history_user_turn_limit": 4,
                "history_message_limit": 7,
                "history_token_budget": 900,
                "rewrite_history_message_limit": 3,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert captured["payload"]["chat_context_enabled"] is True
        assert captured["payload"]["history_user_turn_limit"] == 4
        assert captured["payload"]["history_message_limit"] == 7
        assert captured["payload"]["history_token_budget"] == 900
        assert captured["payload"]["rewrite_history_message_limit"] == 3
        assert payload["chat_context_enabled"] is True
        assert payload["history_user_turn_limit"] == 4
        assert payload["history_message_limit"] == 7
        assert payload["history_token_budget"] == 900
        assert payload["rewrite_history_message_limit"] == 3
    finally:
        app.dependency_overrides.clear()


def test_put_provider_skips_embedding_probe_when_provider_connection_unchanged(monkeypatch):
    from app.api.v1 import admin as admin_module

    captured: dict = {}
    verify_calls = {"count": 0}

    async def _verify_embedding_dimension(**kwargs):
        verify_calls["count"] += 1
        return None

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return SimpleNamespace(
                id="provider-existing",
                tenant_id=tenant_id,
                base_url="https://openrouter.ai/api/v1",
                api_key="encrypted-existing",
                model_name="openai/gpt-4o-mini",
                embedding_model="text-embedding-3-small",
                timeout_s=30,
                retry_policy=2,
                knowledge_mode="glossary_documents",
                empty_retrieval_mode="model_only_fallback",
                strict_glossary_mode=False,
                show_confidence=False,
                show_source_tags=True,
                response_tone="consultative_supportive",
                max_user_messages_total=5,
                chat_context_enabled=True,
                history_user_turn_limit=6,
                history_message_limit=12,
                history_token_budget=1200,
                rewrite_history_message_limit=8,
                updated_at=datetime.now(UTC),
            )

        def upsert_provider(self, tenant_id: str, payload: dict):
            captured["tenant_id"] = tenant_id
            captured["payload"] = payload
            return SimpleNamespace(
                id="provider-existing",
                tenant_id=tenant_id,
                base_url=payload["base_url"],
                api_key=payload["api_key"],
                model_name=payload["model_name"],
                embedding_model=payload["embedding_model"],
                timeout_s=payload["timeout_s"],
                retry_policy=payload["retry_policy"],
                knowledge_mode=payload["knowledge_mode"],
                empty_retrieval_mode=payload["empty_retrieval_mode"],
                strict_glossary_mode=payload["strict_glossary_mode"],
                show_confidence=payload["show_confidence"],
                show_source_tags=payload["show_source_tags"],
                response_tone=payload["response_tone"],
                max_user_messages_total=payload["max_user_messages_total"],
                chat_context_enabled=payload["chat_context_enabled"],
                history_user_turn_limit=payload["history_user_turn_limit"],
                history_message_limit=payload["history_message_limit"],
                history_token_budget=payload["history_token_budget"],
                rewrite_history_message_limit=payload["rewrite_history_message_limit"],
                updated_at=datetime.now(UTC),
            )

        def add_audit_log(self, *args, **kwargs):
            return None

        @staticmethod
        def provider_api_key_plain(row):
            return "sk-existing-provider-key-123456"

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module, "_verify_embedding_dimension", _verify_embedding_dimension)
    monkeypatch.setattr(admin_module, "_validate_provider_base_url_public_sync", lambda base_url: None)

    client = TestClient(app)
    try:
        response = client.put(
            "/api/v1/admin/provider",
            json={
                "base_url": "https://openrouter.ai/api/v1",
                "model_name": "openai/gpt-4o-mini",
                "embedding_model": "text-embedding-3-small",
                "timeout_s": 30,
                "retry_policy": 2,
                "knowledge_mode": "glossary_documents",
                "empty_retrieval_mode": "model_only_fallback",
                "strict_glossary_mode": False,
                "show_confidence": False,
                "show_source_tags": True,
                "response_tone": "neutral_reference",
                "max_user_messages_total": 25,
                "chat_context_enabled": True,
                "history_user_turn_limit": 6,
                "history_message_limit": 12,
                "history_token_budget": 1200,
                "rewrite_history_message_limit": 8,
            },
        )
        assert response.status_code == 200
        assert verify_calls["count"] == 0
        assert captured["payload"]["response_tone"] == "neutral_reference"
        assert captured["payload"]["max_user_messages_total"] == 25
    finally:
        app.dependency_overrides.clear()


def test_put_provider_accepts_real_api_key_containing_asterisk(monkeypatch):
    from app.api.v1 import admin as admin_module

    captured: dict = {}

    async def _verify_embedding_dimension(**kwargs):
        return None

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return None

        def upsert_provider(self, tenant_id: str, payload: dict):
            captured["payload"] = payload
            return SimpleNamespace(
                id="provider-1",
                tenant_id=tenant_id,
                base_url=payload["base_url"],
                api_key=payload["api_key"],
                model_name=payload["model_name"],
                embedding_model=payload["embedding_model"],
                timeout_s=payload["timeout_s"],
                retry_policy=payload["retry_policy"],
                knowledge_mode=payload["knowledge_mode"],
                empty_retrieval_mode=payload["empty_retrieval_mode"],
                strict_glossary_mode=payload["strict_glossary_mode"],
                show_confidence=payload["show_confidence"],
                show_source_tags=payload["show_source_tags"],
                response_tone=payload["response_tone"],
                max_user_messages_total=payload["max_user_messages_total"],
                chat_context_enabled=payload["chat_context_enabled"],
                history_user_turn_limit=payload["history_user_turn_limit"],
                history_message_limit=payload["history_message_limit"],
                history_token_budget=payload["history_token_budget"],
                rewrite_history_message_limit=payload["rewrite_history_message_limit"],
                updated_at=datetime.now(UTC),
            )

        def add_audit_log(self, *args, **kwargs):
            return None

        @staticmethod
        def provider_api_key_plain(row):
            return "sk-old-provider-key-123456"

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module, "_verify_embedding_dimension", _verify_embedding_dimension)
    monkeypatch.setattr(admin_module, "_validate_provider_base_url_public_sync", lambda base_url: None)

    client = TestClient(app)
    try:
        response = client.put(
            "/api/v1/admin/provider",
            json={
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-real*key-contains-star-123456",
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
        )
        assert response.status_code == 200
        assert captured["payload"]["api_key"] == "sk-real*key-contains-star-123456"
    finally:
        app.dependency_overrides.clear()
