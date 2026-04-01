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


def test_admin_token_usage_users_supports_pagination_and_sort(monkeypatch):
    from app.api.v1 import admin as admin_module

    captured: dict[str, int | str] = {}

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def user_token_usage_analytics(
            self,
            tenant_id: str,
            *,
            window_days: int = 30,
            page: int = 1,
            page_size: int = 10,
            sort_order: str = "desc",
            only_with_requests: bool = False,
        ):
            captured["window_days"] = window_days
            captured["page"] = page
            captured["page_size"] = page_size
            captured["sort_order"] = sort_order
            captured["only_with_requests"] = only_with_requests
            now = datetime.now(UTC)
            return {
                "window_days": window_days,
                "sort_order": sort_order,
                "page": page,
                "page_size": page_size,
                "total": 2,
                "items": [
                    {
                        "user_id": "00000000-0000-0000-0000-000000000001",
                        "email": "00000000-0000-0000-0000-000000000001@keycloak.local",
                        "role": "admin",
                        "request_count": 12,
                        "provider_prompt_tokens": 600,
                        "provider_completion_tokens": 400,
                        "provider_total_tokens": 1000,
                        "rewrite_total_tokens": 100,
                        "total_tokens": 1100,
                        "avg_tokens_per_request": 91.67,
                        "last_request_at": now,
                    }
                ],
                "summary": {
                    "month_start": now,
                    "month_end": now,
                    "month_total_tokens": 2000,
                    "month_prompt_tokens": 1200,
                    "month_completion_tokens": 700,
                    "month_rewrite_tokens": 100,
                    "month_request_count": 20,
                    "active_users_in_month": 2,
                    "total_users": 2,
                    "avg_tokens_per_request": 100.0,
                    "avg_tokens_per_active_user": 1000.0,
                    "avg_daily_tokens": 66.67,
                    "projected_month_total_tokens": 2066.77,
                },
            }

    async def fake_resolve_user_emails_from_keycloak(user_ids: list[str], tenant_id: str) -> dict[str, str]:
        assert tenant_id == "00000000-0000-0000-0000-0000000000bb"
        return {user_id: "resolved@example.com" for user_id in user_ids}

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module, "_resolve_user_emails_from_keycloak", fake_resolve_user_emails_from_keycloak)

    client = TestClient(app)
    try:
        response = client.get("/api/v1/admin/analytics/token-usage/users")
        assert response.status_code == 200
        payload = response.json()
        assert captured["window_days"] == 30
        assert captured["page"] == 1
        assert captured["page_size"] == 10
        assert captured["sort_order"] == "desc"
        assert captured["only_with_requests"] is False
        assert payload["items"][0]["role"] == "admin"
        assert payload["items"][0]["email"] == "resolved@example.com"
        assert payload["summary"]["month_total_tokens"] == 2000

        response_with_filters = client.get(
            "/api/v1/admin/analytics/token-usage/users?window_days=90&page=2&page_size=5&sort_order=asc&only_with_requests=true"
        )
        assert response_with_filters.status_code == 200
        assert captured["window_days"] == 90
        assert captured["page"] == 2
        assert captured["page_size"] == 5
        assert captured["sort_order"] == "asc"
        assert captured["only_with_requests"] is True
    finally:
        app.dependency_overrides.clear()
