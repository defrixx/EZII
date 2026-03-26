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
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        embedding_model: str,
        timeout_s: int = 30,
        max_retries: int = 2,
        embedding_base_url: str | None = None,
        embedding_api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.embedding_base_url = (embedding_base_url or "").strip().rstrip("/")
        self.embedding_api_key = (embedding_api_key or "").strip()

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _headers_for_api_key(api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _is_openrouter_embedding_model(model: str) -> bool:
        normalized = str(model or "").strip().lower()
        return normalized.startswith("openai/") or normalized.startswith("text-embedding-")

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

    @staticmethod
    def _embeddings_response_summary(data: dict[str, Any]) -> dict[str, Any]:
        rows = data.get("data")
        total_items = len(rows) if isinstance(rows, list) else 0
        first_item = rows[0] if isinstance(rows, list) and rows else {}
        first_item_keys = sorted([str(key) for key in first_item.keys()]) if isinstance(first_item, dict) else []
        first_embedding_len = None
        if isinstance(first_item, dict) and isinstance(first_item.get("embedding"), list):
            first_embedding_len = len(first_item["embedding"])
        raw_preview = json.dumps(data, ensure_ascii=False, default=str)[:400]
        return {
            "total_items": total_items,
            "first_item_keys": first_item_keys,
            "first_embedding_len": first_embedding_len,
            "raw_preview": raw_preview,
        }

    @staticmethod
    def _provider_error_headers(response: httpx.Response) -> dict[str, str]:
        headers = response.headers
        return {
            "x_request_id": str(headers.get("x-request-id") or ""),
            "openrouter_request_id": str(headers.get("openrouter-request-id") or ""),
            "cf_ray": str(headers.get("cf-ray") or ""),
        }

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.embedding_model, "input": texts}
        use_openrouter = self._is_openrouter_embedding_model(self.embedding_model)
        if use_openrouter:
            embedding_base = self.base_url
            embedding_key = self.api_key
        else:
            embedding_base = self.embedding_base_url or self.base_url
            embedding_key = self.embedding_api_key or self.api_key
        data = await self._post_with_retry_with_optional_api_key(
            f"{embedding_base}/embeddings",
            payload,
            api_key=embedding_key,
        )
        embeddings = [item["embedding"] for item in data.get("data", [])]
        if len(embeddings) == len(texts):
            return embeddings
        summary = self._embeddings_response_summary(data)
        logger.warning(
            "Embedding response shape mismatch model=%s requested=%s received=%s total_items=%s first_item_keys=%s first_embedding_len=%s raw_preview=%s",
            self.embedding_model,
            len(texts),
            len(embeddings),
            summary["total_items"],
            summary["first_item_keys"],
            summary["first_embedding_len"],
            summary["raw_preview"],
        )
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
            single_data = await self._post_with_retry_with_optional_api_key(
                f"{embedding_base}/embeddings",
                single_payload,
                api_key=embedding_key,
            )
            single_embeddings = [item["embedding"] for item in single_data.get("data", [])]
            if len(single_embeddings) != 1:
                single_summary = self._embeddings_response_summary(single_data)
                logger.warning(
                    "Embedding single-item fallback failed model=%s requested=1 received=%s total_items=%s first_item_keys=%s first_embedding_len=%s raw_preview=%s",
                    self.embedding_model,
                    len(single_embeddings),
                    single_summary["total_items"],
                    single_summary["first_item_keys"],
                    single_summary["first_embedding_len"],
                    single_summary["raw_preview"],
                )
                raise RuntimeError("Embedding provider returned inconsistent batch size")
            fallback_embeddings.append(single_embeddings[0])
        return fallback_embeddings

    async def _post_with_retry_with_optional_api_key(self, url: str, payload: dict, api_key: str | None = None) -> dict:
        # Backward-compatible shim for tests that monkeypatch `_post_with_retry`
        # with a 2-argument callable (url, payload).
        post_with_retry = self._post_with_retry
        code = getattr(post_with_retry, "__code__", None)
        argcount = int(getattr(code, "co_argcount", 0) or 0)
        if argcount <= 2:
            return await post_with_retry(url, payload)  # type: ignore[misc]
        return await post_with_retry(url, payload, api_key=api_key)

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
                    except json.JSONDecodeError as exc:
                        raise RuntimeError("Malformed streaming event from provider") from exc
                    if not isinstance(event, dict):
                        raise RuntimeError("Malformed streaming event from provider")
                    usage = event.get("usage")
                    if isinstance(usage, dict) and usage:
                        yield {"type": "usage", "usage": usage}
                    choices = event.get("choices")
                    first_choice = choices[0] if isinstance(choices, list) and choices else {}
                    delta = first_choice.get("delta", {}) if isinstance(first_choice, dict) else {}
                    content = delta.get("content") if isinstance(delta, dict) else None
                    if content:
                        yield {"type": "content", "content": content}

    async def _post_with_retry(self, url: str, payload: dict, api_key: str | None = None) -> dict:
        effective_api_key = str(api_key or self.api_key or "").strip()
        if not effective_api_key:
            raise RuntimeError("Provider API key is not configured")
        delay = 0.5
        for attempt in range(self.max_retries + 1):
            try:
                allowed_ips = await self._guard_provider_host(url)
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    resp = await client.post(url, headers=self._headers_for_api_key(effective_api_key), json=payload)
                    self._assert_peer_ip(resp, allowed_ips)
                    if resp.status_code >= 400:
                        headers = self._provider_error_headers(resp)
                        endpoint = urlparse(url).path
                        try:
                            body_preview = resp.text[:500]
                        except Exception:
                            body_preview = "<failed to read response body>"
                        logger.warning(
                            "Provider request failed status=%s endpoint=%s model=%s x_request_id=%s openrouter_request_id=%s cf_ray=%s body_preview=%s",
                            resp.status_code,
                            endpoint,
                            str(payload.get("model") or ""),
                            headers["x_request_id"],
                            headers["openrouter_request_id"],
                            headers["cf_ray"],
                            body_preview,
                        )
                    resp.raise_for_status()
                    return resp.json()
            except Exception:
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("Provider retry loop failed")
