import asyncio

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
