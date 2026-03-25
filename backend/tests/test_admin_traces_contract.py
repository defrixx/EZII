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


def test_admin_traces_exposes_conversational_context_fields(monkeypatch):
    from app.api.v1 import admin as admin_module
    captured: dict[str, int] = {}

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def list_traces(self, tenant_id: str, limit: int = 100):
            captured["limit"] = limit
            return [
                SimpleNamespace(
                    id="trace-1",
                    chat_id="chat-1",
                    model="stub-model",
                    knowledge_mode="glossary_documents",
                    answer_mode="grounded",
                    source_types=["glossary", "model"],
                    glossary_entries_used=["entry-1"],
                    document_ids=[],
                    web_snapshot_ids=[],
                    web_domains_used=[],
                    ranking_scores={},
                    latency_ms=123.4,
                    token_usage={
                        "chat_context_enabled": False,
                        "rewrite_used": True,
                        "rewritten_query": "what does devsecops mean in our policy",
                        "history_messages_used": 3,
                        "history_token_estimate": 44,
                        "history_trimmed": True,
                    },
                    status="ok",
                    created_at=datetime.now(UTC),
                )
            ]

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)

    client = TestClient(app)
    try:
        response = client.get("/api/v1/admin/traces")
        assert response.status_code == 200
        payload = response.json()
        assert captured["limit"] == 20
        assert payload[0]["chat_context_enabled"] is False
        assert payload[0]["rewrite_used"] is True
        assert payload[0]["rewritten_query"] == "what does devsecops mean in our policy"
        assert payload[0]["history_messages_used"] == 3
        assert payload[0]["history_token_estimate"] == 44
        assert payload[0]["history_trimmed"] is True
        response_with_limit = client.get("/api/v1/admin/traces?limit=7")
        assert response_with_limit.status_code == 200
        assert captured["limit"] == 7
    finally:
        app.dependency_overrides.clear()
