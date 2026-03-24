import asyncio
import json
from typing import Any
import httpx


class OpenRouterProvider:
    def __init__(self, base_url: str, api_key: str, model: str, embedding_model: str, timeout_s: int = 30, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.embedding_model, "input": texts}
        data = await self._post_with_retry(f"{self.base_url}/embeddings", payload)
        return [item["embedding"] for item in data.get("data", [])]

    async def answer(self, messages: list[dict[str, str]], temperature: float = 0.1) -> dict[str, Any]:
        payload = {"model": self.model, "messages": messages, "temperature": temperature}
        return await self._post_with_retry(f"{self.base_url}/chat/completions", payload)

    async def answer_stream(self, messages: list[dict[str, str]], temperature: float = 0.1):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                        usage = event.get("usage")
                        if isinstance(usage, dict) and usage:
                            yield {"type": "usage", "usage": usage}
                        content = event.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content:
                            yield {"type": "content", "content": content}
                    except Exception:
                        continue

    async def _post_with_retry(self, url: str, payload: dict) -> dict:
        delay = 0.5
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    resp = await client.post(url, headers=self.headers, json=payload)
                    resp.raise_for_status()
                    return resp.json()
            except Exception:
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("Provider retry loop failed")
