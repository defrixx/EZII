from fastapi.testclient import TestClient

from app.core.logging_utils import safe_payload
from app.main import app


def test_ready_returns_503_when_any_dependency_is_degraded(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "_dependency_health_report",
        lambda: {
            "status": "degraded",
            "checks": {"postgres": {"ok": True}, "redis": {"ok": False}, "qdrant": {"ok": True}},
        },
    )

    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_health_is_liveness_even_when_dependencies_are_degraded(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "_dependency_health_report",
        lambda: {
            "status": "degraded",
            "checks": {"postgres": {"ok": True}, "redis": {"ok": False}, "qdrant": {"ok": True}},
        },
    )

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_safe_payload_redacts_nested_sensitive_values():
    payload = {
        "query": "Authorization: Bearer very-secret-token-value",
        "token": "plain-secret-token",
        "nested": {
            "access_token": "eyJabc.def.ghi",
            "meta": ["user@example.com", "no secret"],
        },
    }

    sanitized = safe_payload(payload)
    assert sanitized["token"] == "[REDACTED]"
    assert "[REDACTED]" in sanitized["query"]
    assert sanitized["nested"]["access_token"] == "[REDACTED]"
    assert sanitized["nested"]["meta"][0] == "[REDACTED]"
