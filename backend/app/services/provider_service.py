import asyncio
import ipaddress
import json
import logging
import socket
from typing import Any
from urllib.parse import urlparse
import httpx

logger = logging.getLogger(__name__)


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

    @staticmethod
    def _resolve_public_ips_sync(host: str, port: int) -> set[str]:
        lowered = (host or "").strip().lower()
        if not lowered:
            raise RuntimeError("Provider host is empty")
        try:
            infos = socket.getaddrinfo(lowered, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise RuntimeError("Provider host must resolve publicly") from exc
        resolved: set[str] = set()
        for info in infos:
            raw_ip = info[4][0]
            ip = ipaddress.ip_address(raw_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise RuntimeError("Provider host must resolve publicly")
            resolved.add(raw_ip)
        if not resolved:
            raise RuntimeError("Provider host must resolve publicly")
        return resolved

    @staticmethod
    def _response_peer_ip(response: httpx.Response) -> str | None:
        stream = response.extensions.get("network_stream")
        if stream is None:
            return None
        getter = getattr(stream, "get_extra_info", None)
        if not callable(getter):
            return None
        server_addr = getter("server_addr")
        if isinstance(server_addr, tuple) and server_addr:
            return str(server_addr[0])
        return None

    async def _guard_provider_host(self, url: str) -> set[str]:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().lower()
        scheme = (parsed.scheme or "").strip().lower()
        if scheme != "https":
            raise RuntimeError("Provider URL must use https")
        port = parsed.port or 443
        return await asyncio.to_thread(self._resolve_public_ips_sync, host, port)

    @classmethod
    def _assert_peer_ip(cls, response: httpx.Response, allowed_ips: set[str]) -> None:
        peer_ip = cls._response_peer_ip(response)
        if peer_ip is None:
            raise RuntimeError("Provider peer IP verification is unavailable for this transport")
        if peer_ip not in allowed_ips:
            raise RuntimeError("Provider resolved host mismatch")

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.embedding_model, "input": texts}
        data = await self._post_with_retry(f"{self.base_url}/embeddings", payload)
        embeddings = [item["embedding"] for item in data.get("data", [])]
        if len(embeddings) == len(texts):
            return embeddings
        if len(texts) == 1:
            return embeddings

        logger.warning(
            "Embedding provider returned inconsistent batch size: requested=%s received=%s model=%s; falling back to per-item requests",
            len(texts),
            len(embeddings),
            self.embedding_model,
        )
        fallback_embeddings: list[list[float]] = []
        for text in texts:
            single_payload = {"model": self.embedding_model, "input": [text]}
            single_data = await self._post_with_retry(f"{self.base_url}/embeddings", single_payload)
            single_embeddings = [item["embedding"] for item in single_data.get("data", [])]
            if len(single_embeddings) != 1:
                raise RuntimeError("Embedding provider returned inconsistent batch size")
            fallback_embeddings.append(single_embeddings[0])
        return fallback_embeddings

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
        url = f"{self.base_url}/chat/completions"
        allowed_ips = await self._guard_provider_host(url)
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            async with client.stream(
                "POST",
                url,
                headers=self.headers,
                json=payload,
            ) as resp:
                self._assert_peer_ip(resp, allowed_ips)
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
        if not str(self.api_key or "").strip():
            raise RuntimeError("Provider API key is not configured")
        delay = 0.5
        for attempt in range(self.max_retries + 1):
            try:
                allowed_ips = await self._guard_provider_host(url)
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    resp = await client.post(url, headers=self.headers, json=payload)
                    self._assert_peer_ip(resp, allowed_ips)
                    resp.raise_for_status()
                    return resp.json()
            except Exception:
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("Provider retry loop failed")
