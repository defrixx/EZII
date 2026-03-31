import asyncio
import pytest
import types
import httpx

from app.services.provider_service import OpenRouterProvider


def test_embeddings_falls_back_to_per_item_when_batch_size_is_inconsistent(monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )
    calls: list[dict] = []

    async def _post(url: str, payload: dict) -> dict:
        calls.append(payload)
        batch_input = payload.get("input")
        if isinstance(batch_input, list) and len(batch_input) == 3:
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        if batch_input == ["alpha"]:
            return {"data": [{"embedding": [1.0]}]}
        if batch_input == ["beta"]:
            return {"data": [{"embedding": [2.0]}]}
        if batch_input == ["gamma"]:
            return {"data": [{"embedding": [3.0]}]}
        raise AssertionError(f"Unexpected payload: {payload}")

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    out = asyncio.run(provider.embeddings(["alpha", "beta", "gamma"]))

    assert out == [[1.0], [2.0], [3.0]]
    assert [payload["input"] for payload in calls] == [
        ["alpha", "beta", "gamma"],
        ["alpha"],
        ["beta"],
        ["gamma"],
    ]


def test_embeddings_logs_response_shape_mismatch(caplog, monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )

    async def _post(url: str, payload: dict) -> dict:
        return {"data": [], "error": {"message": "no embeddings"}}

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    with caplog.at_level("WARNING"):
        out = asyncio.run(provider.embeddings(["alpha"]))

    assert out == []
    assert "Embedding response shape mismatch" in caplog.text
    assert "error_code" in caplog.text
    assert "raw_preview" not in caplog.text


def test_embeddings_falls_back_to_per_item_on_413(monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )
    calls: list[list[str]] = []

    async def _post(url: str, payload: dict) -> dict:
        batch_input = payload.get("input")
        if not isinstance(batch_input, list):
            raise AssertionError(f"Unexpected payload: {payload}")
        calls.append(batch_input)
        if len(batch_input) > 1:
            request = httpx.Request("POST", url)
            response = httpx.Response(status_code=413, request=request)
            raise httpx.HTTPStatusError("413 Request Entity Too Large", request=request, response=response)
        return {"data": [{"embedding": [float(len(batch_input[0]))]}]}

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    out = asyncio.run(provider.embeddings(["alpha", "beta"]))

    assert out == [[5.0], [4.0]]
    assert calls == [["alpha", "beta"], ["alpha"], ["beta"]]


def test_embeddings_splits_large_requests_into_fixed_size_batches(monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )
    provider._EMBEDDING_BATCH_MAX_ITEMS = 140
    batch_sizes: list[int] = []

    async def _post(url: str, payload: dict) -> dict:
        batch_input = payload.get("input")
        if not isinstance(batch_input, list):
            raise AssertionError(f"Unexpected payload: {payload}")
        batch_sizes.append(len(batch_input))
        return {"data": [{"embedding": [float(i)]} for i, _ in enumerate(batch_input)]}

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    inputs = [f"chunk-{i}" for i in range(360)]
    out = asyncio.run(provider.embeddings(inputs))

    assert len(out) == 360
    assert batch_sizes == [140, 140, 80]
    assert out[0] == [0.0]
    assert out[139] == [139.0]
    assert out[140] == [0.0]
    assert out[279] == [139.0]
    assert out[280] == [0.0]
    assert out[359] == [79.0]


def test_embeddings_splits_very_large_requests_and_preserves_global_order(monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )
    provider._EMBEDDING_BATCH_MAX_ITEMS = 140
    batch_sizes: list[int] = []

    async def _post(url: str, payload: dict) -> dict:
        batch_input = payload.get("input")
        if not isinstance(batch_input, list):
            raise AssertionError(f"Unexpected payload: {payload}")
        batch_sizes.append(len(batch_input))
        vectors = []
        for item in batch_input:
            idx = int(str(item).split("-", 1)[1])
            vectors.append({"embedding": [float(idx)]})
        return {"data": vectors}

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    inputs = [f"chunk-{i}" for i in range(1200)]
    out = asyncio.run(provider.embeddings(inputs))

    assert len(out) == 1200
    assert batch_sizes == [140, 140, 140, 140, 140, 140, 140, 140, 80]
    assert out[0] == [0.0]
    assert out[139] == [139.0]
    assert out[140] == [140.0]
    assert out[1119] == [1119.0]
    assert out[1120] == [1120.0]
    assert out[1199] == [1199.0]


def test_embeddings_single_item_413_splits_text_and_recovers(monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )
    provider._EMBEDDING_413_MIN_SPLIT_CHARS = 2
    provider._EMBEDDING_413_MAX_SPLIT_DEPTH = 8

    async def _post(url: str, payload: dict) -> dict:
        batch_input = payload.get("input")
        if not isinstance(batch_input, list) or len(batch_input) != 1:
            raise AssertionError(f"Unexpected payload: {payload}")
        text = str(batch_input[0])
        if len(text) > 6:
            request = httpx.Request("POST", url)
            response = httpx.Response(status_code=413, request=request)
            raise httpx.HTTPStatusError("413 Request Entity Too Large", request=request, response=response)
        return {"data": [{"embedding": [float(len(text))]}]}

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    out = asyncio.run(provider.embeddings(["abcdefghij"]))

    assert len(out) == 1
    # Split will produce 5 + 5 and weighted average should keep value 5.0.
    assert out[0] == [5.0]


def test_embeddings_single_item_413_truncates_when_split_depth_exhausted(monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )
    provider._EMBEDDING_413_MIN_SPLIT_CHARS = 4
    provider._EMBEDDING_413_MAX_SPLIT_DEPTH = 0

    async def _post(url: str, payload: dict) -> dict:
        batch_input = payload.get("input")
        if not isinstance(batch_input, list) or len(batch_input) != 1:
            raise AssertionError(f"Unexpected payload: {payload}")
        text = str(batch_input[0])
        if len(text) > 8:
            request = httpx.Request("POST", url)
            response = httpx.Response(status_code=413, request=request)
            raise httpx.HTTPStatusError("413 Request Entity Too Large", request=request, response=response)
        return {"data": [{"embedding": [42.0]}]}

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    out = asyncio.run(provider.embeddings(["abcdefghijklmno"]))

    assert out == [[42.0]]


def test_embeddings_single_item_413_truncates_below_min_split_threshold(monkeypatch):
    provider = OpenRouterProvider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )
    provider._EMBEDDING_413_MIN_SPLIT_CHARS = 200
    provider._EMBEDDING_413_MAX_SPLIT_DEPTH = 0
    provider._EMBEDDING_413_MAX_TRUNCATION_ATTEMPTS = 12

    async def _post(url: str, payload: dict) -> dict:
        batch_input = payload.get("input")
        if not isinstance(batch_input, list) or len(batch_input) != 1:
            raise AssertionError(f"Unexpected payload: {payload}")
        text = str(batch_input[0])
        if len(text) > 2:
            request = httpx.Request("POST", url)
            response = httpx.Response(status_code=413, request=request)
            raise httpx.HTTPStatusError("413 Request Entity Too Large", request=request, response=response)
        return {"data": [{"embedding": [99.0]}]}

    monkeypatch.setattr(provider, "_post_with_retry", _post)

    out = asyncio.run(provider.embeddings(["abcdefghij"]))

    assert out == [[99.0]]


def test_provider_host_guard_rejects_non_https_urls():
    provider = OpenRouterProvider(
        base_url="http://openrouter.example/api/v1",
        api_key="test-key",
        model="openai/gpt-test",
        embedding_model="openai/embedding-test",
    )

    with pytest.raises(RuntimeError, match="https"):
        asyncio.run(provider._guard_provider_host("http://openrouter.example/api/v1/chat/completions"))


def test_peer_ip_check_rejects_when_transport_does_not_expose_peer_ip():
    response = types.SimpleNamespace(extensions={})
    with pytest.raises(RuntimeError, match="verification is unavailable"):
        OpenRouterProvider._assert_peer_ip(response, {"203.0.113.10"})


def test_peer_ip_check_rejects_mismatched_ip():
    class Stream:
        @staticmethod
        def get_extra_info(name: str):
            if name == "server_addr":
                return ("203.0.113.77", 443)
            return None

    response = types.SimpleNamespace(extensions={"network_stream": Stream()})
    with pytest.raises(RuntimeError, match="resolved host mismatch"):
        OpenRouterProvider._assert_peer_ip(response, {"203.0.113.10"})


def test_provider_error_headers_extracts_diagnostic_ids():
    response = types.SimpleNamespace(
        headers={
            "x-request-id": "req_123",
            "openrouter-request-id": "or_456",
            "cf-ray": "ray_789",
        }
    )
    headers = OpenRouterProvider._provider_error_headers(response)  # type: ignore[arg-type]
    assert headers["x_request_id"] == "req_123"
    assert headers["openrouter_request_id"] == "or_456"
    assert headers["cf_ray"] == "ray_789"
