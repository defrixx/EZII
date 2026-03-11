from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_removed_non_stream_messages_endpoint_returns_404():
    response = client.post("/api/v1/messages/chat-1", json={"content": "ping"})
    assert response.status_code == 404


def test_removed_admin_retrieval_test_endpoint_returns_404():
    response = client.post(
        "/api/v1/admin/retrieval-test",
        json={"query": "test", "web_enabled": False, "strict_glossary_mode": False},
    )
    assert response.status_code == 404
