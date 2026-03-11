import types

from fastapi.testclient import TestClient

from app.core.security import AuthContext
from app.main import app


def _auth_ctx() -> AuthContext:
    return AuthContext(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        email="user@example.com",
        role="user",
    )


def test_messages_stream_emits_trace_and_done(monkeypatch):
    from app.api.v1 import messages as messages_module

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def run(self, tenant_id: str, query: str, strict_glossary_mode: bool, web_enabled: bool):
            return {
                "intent": "semantic_lookup",
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.9}],
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(self, provider, query: str, context: str, strict_glossary_mode: bool, response_tone: str, intent: str):
            yield "Привет"
            yield " мир"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            strict_glossary_mode=False,
            web_enabled=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", lambda *args, **kwargs: "trace-123")
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "тест"},
        )
        assert response.status_code == 200
        assert response.headers.get("x-accel-buffering") == "no"
        assert "data: Привет" in response.text
        assert "data:  мир" in response.text
        assert "event: trace\ndata: trace-123" in response.text
        assert "data: [DONE]" in response.text
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_emits_error_event_on_runtime_failure(monkeypatch):
    from app.api.v1 import messages as messages_module

    class FailingRetrievalService:
        def __init__(self):
            pass

        async def run(self, tenant_id: str, query: str, strict_glossary_mode: bool, web_enabled: bool):
            raise RuntimeError("provider down")

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            strict_glossary_mode=False,
            web_enabled=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_error_trace_sync", lambda *args, **kwargs: None)
    monkeypatch.setattr(messages_module, "RetrievalService", FailingRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "тест"},
        )
        assert response.status_code == 200
        assert "event: error" in response.text
        assert "Ошибка обработки запроса" in response.text
        assert "data: [DONE]" in response.text
    finally:
        app.dependency_overrides.clear()
