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


def test_admin_logs_respects_limit_query_param(monkeypatch):
    from app.api.v1 import admin as admin_module

    captured: dict[str, int] = {}

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def list_error_logs(self, tenant_id: str, limit: int = 100):
            captured["limit"] = limit
            return [
                SimpleNamespace(
                    id="err-1",
                    error_type="provider_or_retrieval_error",
                    message="Stub error",
                    created_at=datetime.now(UTC),
                )
            ]

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)

    client = TestClient(app)
    try:
        response = client.get("/api/v1/admin/logs")
        assert response.status_code == 200
        assert captured["limit"] == 20
        payload = response.json()
        assert payload[0]["type"] == "provider_or_retrieval_error"

        response_with_limit = client.get("/api/v1/admin/logs?limit=6")
        assert response_with_limit.status_code == 200
        assert captured["limit"] == 6
    finally:
        app.dependency_overrides.clear()
