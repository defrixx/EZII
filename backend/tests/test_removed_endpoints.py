from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_removed_non_stream_messages_endpoint_returns_404():
    response = client.post("/api/v1/messages/chat-1", json={"content": "ping"})
    assert response.status_code == 404


def test_removed_glossary_bulk_import_endpoint_returns_404():
    response = client.post(
        "/api/v1/glossary/00000000-0000-0000-0000-000000000000/import",
        json={"rows": []},
    )
    assert response.status_code == 404
