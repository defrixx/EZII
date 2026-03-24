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

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool, web_enabled: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.9}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary", "model"],
                "ranking_scores": {"glossary": {"entry-1": 0.9}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(self, provider, query: str, context: str, knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield "Привет"
            yield " мир"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
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

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool, web_enabled: bool):
            raise RuntimeError("provider down")

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
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


def test_messages_stream_persists_metrics_and_fallback_reason(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool, web_enabled: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.91}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary", "model"],
                "ranking_scores": {"glossary": {"entry-1": 0.91}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(self, provider, query: str, context: str, knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield {"type": "content", "content": "Привет"}
            yield {"type": "usage", "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics):
        captured["answer"] = answer
        captured["source_types"] = source_types
        captured["metrics"] = metrics
        return "trace-metrics"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            web_enabled=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", _persist_assistant_result_sync)
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
      response = client.post(
          "/api/v1/messages/chat-1/stream",
          json={"content": "тест"},
      )
      assert response.status_code == 200
      assert "event: trace\ndata: trace-metrics" in response.text
      assert '"source_types": ["glossary", "model"]' in response.text
      metrics = captured["metrics"]
      assert metrics.stream_chunks == 1
      assert metrics.provider_usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
      assert metrics.fallback_reason is None
      assert metrics.total_latency_ms >= 0
      assert metrics.retrieval_latency_ms >= 0
      assert metrics.generation_latency_ms >= 0
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_emits_document_and_website_ids_in_retrieval_trace(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool, web_enabled: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": ["vendor.example.com"],
                "top_glossary": [{"id": "entry-1", "score": 0.96}],
                "top_documents": [{"id": "chunk-1", "document_id": "doc-1", "score": 0.81}],
                "top_websites": [{"id": "site-chunk-1", "web_snapshot_id": "site-1", "score": 0.74}],
                "document_ids": ["doc-1"],
                "web_snapshot_ids": ["site-1"],
                "source_types": ["glossary", "document", "website", "model"],
                "ranking_scores": {
                    "glossary": {"entry-1": 0.96},
                    "documents": {"chunk-1": 0.81},
                    "website_snapshots": {"site-chunk-1": 0.74},
                },
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "high",
            }

        async def stream_answer(self, provider, query: str, context: str, knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield {"type": "content", "content": "Ответ с источниками"}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics):
        captured["source_types"] = source_types
        captured["document_ids"] = res["document_ids"]
        captured["web_snapshot_ids"] = res["web_snapshot_ids"]
        return "trace-with-sources"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents_web",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            web_enabled=True,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", _persist_assistant_result_sync)
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "тест"},
        )
        assert response.status_code == 200
        assert '"document_ids": ["doc-1"]' in response.text
        assert '"web_snapshot_ids": ["site-1"]' in response.text
        assert '"source_types": ["glossary", "document", "website", "model"]' in response.text
        assert captured["document_ids"] == ["doc-1"]
        assert captured["web_snapshot_ids"] == ["site-1"]
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_marks_fallback_when_no_retrieval_context(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool, web_enabled: bool):
            return {
                "intent": "web_assisted",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["model"],
                "ranking_scores": {"glossary": {}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "",
                "confidence": "low",
            }

        async def stream_answer(self, provider, query: str, context: str, knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            assert answer_mode == "strict_fallback"
            if False:
                yield {"type": "content", "content": ""}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics):
        captured["answer"] = answer
        captured["metrics"] = metrics
        return "trace-fallback"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="strict_fallback",
            strict_glossary_mode=False,
            web_enabled=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", _persist_assistant_result_sync)
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "тест"},
        )
        assert response.status_code == 200
        assert "data: [DONE]" in response.text
        metrics = captured["metrics"]
        assert metrics.fallback_reason == "no_retrieval_context"
        assert metrics.answer_mode == "strict_fallback"
        assert metrics.stream_chunks == 0
        assert metrics.total_latency_ms >= 0
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_uses_model_only_fallback_when_configured(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool, web_enabled: bool):
            return {
                "intent": "web_assisted",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["model"],
                "ranking_scores": {"glossary": {}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "",
                "confidence": "low",
            }

        async def stream_answer(self, provider, query: str, context: str, knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            captured["answer_mode_from_prompt"] = answer_mode
            captured["context"] = context
            yield {"type": "content", "content": "В базе знаний ничего не найдено. Могу ответить как общий помощник."}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics):
        captured["answer"] = answer
        captured["metrics"] = metrics
        return "trace-model-only"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            web_enabled=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", _persist_assistant_result_sync)
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "тест"},
        )
        assert response.status_code == 200
        assert '"answer_mode": "model_only"' in response.text
        assert '"fallback_reason": "no_retrieval_context"' in response.text
        assert captured["answer_mode_from_prompt"] == "model_only"
        assert captured["context"] == ""
        assert captured["metrics"].fallback_reason == "no_retrieval_context"
        assert captured["metrics"].answer_mode == "model_only"
    finally:
        app.dependency_overrides.clear()
