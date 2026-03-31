import types

from fastapi import HTTPException
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

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.9}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary"],
                "ranking_scores": {"glossary": {"entry-1": 0.9}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield "Hello"
            yield " world"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
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
            json={"content": "test"},
        )
        assert response.status_code == 200
        assert response.headers.get("x-accel-buffering") == "no"
        assert "data: Hello" in response.text
        assert "data:  world" in response.text
        assert "event: trace\ndata: trace-123" in response.text
        assert "event: trusted_html" in response.text
        assert "data: [DONE]" in response.text
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_emits_error_event_on_runtime_failure(monkeypatch):
    from app.api.v1 import messages as messages_module

    class FailingRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
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
            json={"content": "test"},
        )
        assert response.status_code == 200
        assert "event: error" in response.text
        assert "Request processing failed" in response.text
        assert "data: [DONE]" in response.text
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_persists_metrics_and_fallback_reason(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.91}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary"],
                "ranking_scores": {"glossary": {"entry-1": 0.91}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield {"type": "content", "content": "Hello"}
            yield {"type": "usage", "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics, prep):
        captured["answer"] = answer
        captured["source_types"] = source_types
        captured["metrics"] = metrics
        captured["prep"] = prep
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
            json={"content": "test"},
        )
        assert response.status_code == 200
        assert "event: trace\ndata: trace-metrics" in response.text
        assert '"source_types": ["glossary"]' in response.text
        metrics = captured["metrics"]
        assert captured["prep"].chat_context_enabled is True
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

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": ["vendor.example.com"],
                "top_glossary": [{"id": "entry-1", "score": 0.96}],
                "top_documents": [{"id": "chunk-1", "document_id": "doc-1", "score": 0.81}],
                "top_websites": [{"id": "site-chunk-1", "web_snapshot_id": "site-1", "score": 0.74}],
                "document_ids": ["doc-1"],
                "web_snapshot_ids": ["site-1"],
                "source_types": ["glossary", "document", "website"],
                "ranking_scores": {
                    "glossary": {"entry-1": 0.96},
                    "documents": {"chunk-1": 0.81},
                    "website_snapshots": {"site-chunk-1": 0.74},
                },
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "high",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield {"type": "content", "content": "Answer with sources"}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics, prep):
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
            json={"content": "test"},
        )
        assert response.status_code == 200
        assert '"document_ids": ["doc-1"]' in response.text
        assert '"web_snapshot_ids": ["site-1"]' in response.text
        assert '"source_types": ["glossary", "document", "website"]' in response.text
        assert captured["document_ids"] == ["doc-1"]
        assert captured["web_snapshot_ids"] == ["site-1"]
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_does_not_duplicate_confidence_line(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.96}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "document_titles": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary"],
                "ranking_scores": {"glossary": {"entry-1": 0.96}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "high",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield {"type": "content", "content": "Answer text.\n\nConfidence level: medium"}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics, prep):
        captured["answer"] = answer
        return "trace-confidence"

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            show_confidence=True,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", _persist_assistant_result_sync)
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "test"},
        )
        assert response.status_code == 200
        # Validate token stream itself does not duplicate confidence line.
        # `trusted_html` event may also contain the same final text representation.
        assert response.text.count("data: Confidence level: medium") == 1
        assert "Confidence level: high" not in response.text
        assert captured["answer"].count("Confidence level: medium") == 1
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_marks_fallback_when_no_retrieval_context(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
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

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            assert answer_mode == "strict_fallback"
            if False:
                yield {"type": "content", "content": ""}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics, prep):
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
            json={"content": "test"},
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


def test_messages_stream_returns_http_error_before_stream_start_on_preflight_failure(monkeypatch):
    from app.api.v1 import messages as messages_module

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)

    def _fail_prepare(ctx, chat_id, payload):
        raise HTTPException(status_code=404, detail="Chat not found")

    monkeypatch.setattr(messages_module, "_prepare_message_request_sync", _fail_prepare)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-404/stream",
            json={"content": "test"},
        )
        assert response.status_code == 404
        payload = response.json()
        assert payload["detail"] == "Chat not found"
        assert payload["error"]["code"] == "http_error"
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_encodes_multiline_chunks_as_sse_data_lines(monkeypatch):
    from app.api.v1 import messages as messages_module

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.9}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary"],
                "ranking_scores": {"glossary": {"entry-1": 0.9}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield {"type": "content", "content": "line-1\nline-2"}

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", lambda *args, **kwargs: "trace-multiline")
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "test"},
        )
        assert response.status_code == 200
        assert "data: line-1\ndata: line-2" in response.text
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_sanitizes_zero_width_chars_and_emits_trusted_html(monkeypatch):
    from app.api.v1 import messages as messages_module

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.9}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary"],
                "ranking_scores": {"glossary": {"entry-1": 0.9}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            yield {"type": "content", "content": "text\u200b [x](javascript:alert(1)) [safe](https://example.com)"}

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", lambda *args, **kwargs: "trace-sanitize")
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "test"},
        )
        assert response.status_code == 200
        assert "\u200b" not in response.text
        assert "event: trusted_html" in response.text
        assert "javascript:alert(1)" not in response.text
        assert "nofollow ugc noopener noreferrer" in response.text
    finally:
        app.dependency_overrides.clear()


def test_sse_data_keeps_trailing_newline_tokens():
    from app.api.v1 import messages as messages_module

    encoded = messages_module._sse_data("header\n")
    assert encoded == "data: header\ndata: \n\n"


def test_messages_stream_uses_model_only_fallback_when_configured(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "web_assisted",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": [],
                "ranking_scores": {"glossary": {}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "",
                "confidence": "low",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            captured["answer_mode_from_prompt"] = answer_mode
            captured["context"] = context
            captured["conversation_history"] = conversation_history
            yield {"type": "content", "content": "Nothing relevant was found in the knowledge base. I can still answer as a general assistant."}

    def _persist_assistant_result_sync(ctx, chat_id, answer, source_types, res, metrics, prep):
        captured["answer"] = answer
        captured["metrics"] = metrics
        captured["source_types"] = source_types
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
            json={"content": "test"},
        )
        assert response.status_code == 200
        assert '"answer_mode": "model_only"' in response.text
        assert '"fallback_reason": "no_retrieval_context"' in response.text
        assert captured["answer_mode_from_prompt"] == "model_only"
        assert captured["context"] == ""
        assert captured["conversation_history"] == []
        assert captured["source_types"] == ["model"]
        assert captured["metrics"].fallback_reason == "no_retrieval_context"
        assert captured["metrics"].answer_mode == "model_only"
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_uses_rewritten_query_and_history_in_prompt(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            captured["rewrite_query_input"] = query
            captured["rewrite_history"] = conversation_history
            return "what does devsecops mean in our policy", {"prompt_tokens": 9}, 12.5

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            captured["retrieval_query"] = query
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.94}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary"],
                "ranking_scores": {"glossary": {"entry-1": 0.94}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "high",
            }

        async def stream_answer(self, provider, query: str, context: str, conversation_history: list[dict[str, str]], knowledge_mode: str, strict_glossary_mode: bool, response_tone: str, intent: str, answer_mode: str = "grounded"):
            captured["generation_query"] = query
            captured["generation_history"] = conversation_history
            yield {"type": "content", "content": "Answer"}

    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(
        messages_module,
        "_prepare_message_request_sync",
        lambda ctx, chat_id, payload: messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            show_confidence=False,
            response_tone="consultative_supportive",
            conversation_history=[
                {"role": "user", "content": "What does DevSecOps mean?"},
                {"role": "assistant", "content": "It is the integration of security practices into DevOps."},
            ],
            history_messages_used=2,
            history_token_estimate=20,
            history_trimmed=False,
        ),
    )
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", lambda *args, **kwargs: "trace-rewrite")
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "how is this interpreted in our policy?"},
        )
        assert response.status_code == 200
        assert captured["rewrite_query_input"] == "how is this interpreted in our policy?"
        assert captured["retrieval_query"] == "what does devsecops mean in our policy"
        assert captured["generation_query"] == "how is this interpreted in our policy?"
        assert len(captured["generation_history"]) == 2
        assert '"rewritten_query": "what does devsecops mean in our policy"' in response.text
        assert '"rewrite_used": true' in response.text
        assert '"history_messages_used": 2' in response.text
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_rejects_cookie_auth_without_origin_and_csrf(monkeypatch):
    from app.api.v1 import messages as messages_module

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)

    client = TestClient(app)
    try:
        client.cookies.set("access_token", "dummy")
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "test"},
        )
        assert response.status_code == 403
        assert response.json().get("detail")
    finally:
        app.dependency_overrides.clear()


def test_messages_stream_passes_is_retry_flag_to_prepare_stage(monkeypatch):
    from app.api.v1 import messages as messages_module

    captured: dict = {}

    class DummyRetrievalService:
        def __init__(self):
            pass

        async def rewrite_query(self, tenant_id: str, query: str, conversation_history: list[dict[str, str]]):
            return query, {}, 0.0

        async def run(self, tenant_id: str, query: str, knowledge_mode: str, strict_glossary_mode: bool):
            return {
                "intent": "semantic_lookup",
                "knowledge_mode": knowledge_mode,
                "web_domains_used": [],
                "top_glossary": [{"id": "entry-1", "score": 0.9}],
                "top_documents": [],
                "top_websites": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "source_types": ["glossary"],
                "ranking_scores": {"glossary": {"entry-1": 0.9}, "documents": {}, "website_snapshots": {}},
                "provider": types.SimpleNamespace(model="stub-model"),
                "assembled_context": "ctx",
                "confidence": "medium",
            }

        async def stream_answer(
            self,
            provider,
            query: str,
            context: str,
            conversation_history: list[dict[str, str]],
            knowledge_mode: str,
            strict_glossary_mode: bool,
            response_tone: str,
            intent: str,
            answer_mode: str = "grounded",
        ):
            yield {"type": "content", "content": "ok"}

    def _prepare(ctx, chat_id, payload):
        captured["is_retry"] = payload.is_retry
        return messages_module.PreparedMessageContext(
            knowledge_mode="glossary_documents",
            empty_retrieval_mode="model_only_fallback",
            strict_glossary_mode=False,
            show_confidence=False,
            response_tone="consultative_supportive",
        )

    app.dependency_overrides[messages_module.auth_dep] = _auth_ctx
    monkeypatch.setattr(messages_module, "check_rate_limit", lambda request, tenant_id, user_id: None)
    monkeypatch.setattr(messages_module, "_prepare_message_request_sync", _prepare)
    monkeypatch.setattr(messages_module, "_persist_assistant_result_sync", lambda *args, **kwargs: "trace-retry")
    monkeypatch.setattr(messages_module, "RetrievalService", DummyRetrievalService)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/messages/chat-1/stream",
            json={"content": "test", "is_retry": True},
        )
        assert response.status_code == 200
        assert captured["is_retry"] is True
    finally:
        app.dependency_overrides.clear()
