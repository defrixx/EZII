from datetime import UTC, datetime

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


def test_admin_source_impact_exposes_top_and_never_used(monkeypatch):
    from app.api.v1 import admin as admin_module
    captured: dict[str, int] = {}

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def source_impact_analytics(self, tenant_id: str, *, window_days: int = 30, limit: int = 10):
            captured["window_days"] = window_days
            captured["limit"] = limit
            now = datetime.now(UTC)
            return {
                "window_days": window_days,
                "total_sources": 3,
                "used_sources": 1,
                "unused_sources": 2,
                "top_used": [
                    {
                        "id": "doc-1",
                        "title": "SOC2 policy",
                        "source_type": "upload",
                        "status": "approved",
                        "enabled_in_retrieval": True,
                        "usage_count": 4,
                        "last_used_at": now,
                        "updated_at": now,
                    }
                ],
                "never_used": [
                    {
                        "id": "doc-2",
                        "title": "Legacy runbook",
                        "source_type": "upload",
                        "status": "draft",
                        "enabled_in_retrieval": False,
                        "usage_count": 0,
                        "last_used_at": None,
                        "updated_at": now,
                    }
                ],
                "metrics": [
                    {"source_id": "doc-1", "usage_count": 4, "last_used_at": now},
                    {"source_id": "doc-2", "usage_count": 0, "last_used_at": None},
                ],
            }

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)

    client = TestClient(app)
    try:
        response = client.get("/api/v1/admin/analytics/source-impact?window_days=14&limit=5")
        assert response.status_code == 200
        payload = response.json()
        assert captured["window_days"] == 14
        assert captured["limit"] == 5
        assert payload["total_sources"] == 3
        assert payload["used_sources"] == 1
        assert payload["unused_sources"] == 2
        assert payload["top_used"][0]["id"] == "doc-1"
        assert payload["never_used"][0]["id"] == "doc-2"
        assert payload["metrics"][0]["source_id"] == "doc-1"
    finally:
        app.dependency_overrides.clear()
