import asyncio
import hashlib
import inspect
import ipaddress
import json
import logging
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse
import httpx

logger = logging.getLogger(__name__)
_EMBEDDING_OAUTH_CACHE: dict[str, tuple[str, float]] = {}
_EMBEDDING_OAUTH_LOCKS: dict[str, asyncio.Lock] = {}


class OpenRouterProvider:
    _EMBEDDING_413_MIN_SPLIT_CHARS = 200
    _EMBEDDING_413_MAX_SPLIT_DEPTH = 6

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
        embedding_oauth_url: str | None = None,
        embedding_oauth_scope: str | None = None,
        embedding_ca_bundle_path: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.embedding_base_url = (embedding_base_url or "").strip().rstrip("/")
        self.embedding_api_key = (embedding_api_key or "").strip()
        self.embedding_oauth_url = (
            (embedding_oauth_url or "https://ngw.devices.sberbank.ru:9443/api/v2/oauth").strip().rstrip("/")
        )
        self.embedding_oauth_scope = (embedding_oauth_scope or "GIGACHAT_API_PERS").strip() or "GIGACHAT_API_PERS"
        self.embedding_ca_bundle_path = (embedding_ca_bundle_path or "").strip()

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
        error_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
        error_code = str(error_obj.get("code") or "")
        error_message = str(error_obj.get("message") or "")
        return {
            "total_items": total_items,
            "first_item_keys": first_item_keys,
            "first_embedding_len": first_embedding_len,
            "error_code": error_code,
            "error_message_len": len(error_message),
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
            embedding_verify: bool | str | None = None
        else:
            embedding_base = self.embedding_base_url or self.base_url
            embedding_key = await self._resolve_non_openrouter_embedding_key()
            embedding_verify = self._embedding_verify()
        embeddings_url = f"{embedding_base}/embeddings"
        try:
            data = await self._post_with_retry_with_optional_api_key(
                embeddings_url,
                payload,
                api_key=embedding_key,
                verify=embedding_verify,
            )
        except httpx.HTTPStatusError as exc:
            status_code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
            if status_code == 413:
                logger.warning(
                    "Embedding batch rejected with 413 model=%s requested=%s; falling back to per-item requests",
                    self.embedding_model,
                    len(texts),
                )
                return await self._embeddings_per_item_fallback(
                    embeddings_url=embeddings_url,
                    texts=texts,
                    embedding_key=embedding_key,
                    embedding_verify=embedding_verify,
                )
            raise
        embeddings = [item["embedding"] for item in data.get("data", [])]
        if len(embeddings) == len(texts):
            return embeddings
        summary = self._embeddings_response_summary(data)
        logger.warning(
            "Embedding response shape mismatch model=%s requested=%s received=%s total_items=%s first_item_keys=%s first_embedding_len=%s error_code=%s error_message_len=%s",
            self.embedding_model,
            len(texts),
            len(embeddings),
            summary["total_items"],
            summary["first_item_keys"],
            summary["first_embedding_len"],
            summary["error_code"],
            summary["error_message_len"],
        )
        if len(texts) == 1:
            return embeddings

        logger.warning(
            "Embedding provider returned inconsistent batch size: requested=%s received=%s model=%s; falling back to per-item requests",
            len(texts),
            len(embeddings),
            self.embedding_model,
        )
        return await self._embeddings_per_item_fallback(
            embeddings_url=embeddings_url,
            texts=texts,
            embedding_key=embedding_key,
            embedding_verify=embedding_verify,
        )

    async def _embeddings_per_item_fallback(
        self,
        *,
        embeddings_url: str,
        texts: list[str],
        embedding_key: str | None,
        embedding_verify: bool | str | None,
    ) -> list[list[float]]:
        fallback_embeddings: list[list[float]] = []
        for text in texts:
            single_embedding = await self._embed_single_text_resilient(
                embeddings_url=embeddings_url,
                text=text,
                embedding_key=embedding_key,
                embedding_verify=embedding_verify,
                split_depth=0,
            )
            fallback_embeddings.append(single_embedding)
        return fallback_embeddings

    async def _embed_single_text_resilient(
        self,
        *,
        embeddings_url: str,
        text: str,
        embedding_key: str | None,
        embedding_verify: bool | str | None,
        split_depth: int,
    ) -> list[float]:
        single_payload = {"model": self.embedding_model, "input": [text]}
        try:
            single_data = await self._post_with_retry_with_optional_api_key(
                embeddings_url,
                single_payload,
                api_key=embedding_key,
                verify=embedding_verify,
            )
        except httpx.HTTPStatusError as exc:
            status_code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
            can_split = (
                status_code == 413
                and len(text) >= self._EMBEDDING_413_MIN_SPLIT_CHARS
                and split_depth < self._EMBEDDING_413_MAX_SPLIT_DEPTH
            )
            if not can_split:
                raise
            left, right = self._split_text_middle(text)
            if not left or not right:
                raise
            logger.warning(
                "Embedding single text rejected with 413 model=%s text_len=%s split_depth=%s; splitting and retrying",
                self.embedding_model,
                len(text),
                split_depth,
            )
            left_embedding = await self._embed_single_text_resilient(
                embeddings_url=embeddings_url,
                text=left,
                embedding_key=embedding_key,
                embedding_verify=embedding_verify,
                split_depth=split_depth + 1,
            )
            right_embedding = await self._embed_single_text_resilient(
                embeddings_url=embeddings_url,
                text=right,
                embedding_key=embedding_key,
                embedding_verify=embedding_verify,
                split_depth=split_depth + 1,
            )
            return self._weighted_average_embeddings(
                [left_embedding, right_embedding],
                [max(1, len(left)), max(1, len(right))],
            )

        single_embeddings = [item["embedding"] for item in single_data.get("data", [])]
        if len(single_embeddings) != 1:
            single_summary = self._embeddings_response_summary(single_data)
            logger.warning(
                "Embedding single-item fallback failed model=%s requested=1 received=%s total_items=%s first_item_keys=%s first_embedding_len=%s error_code=%s error_message_len=%s",
                self.embedding_model,
                len(single_embeddings),
                single_summary["total_items"],
                single_summary["first_item_keys"],
                single_summary["first_embedding_len"],
                single_summary["error_code"],
                single_summary["error_message_len"],
            )
            raise RuntimeError("Embedding provider returned inconsistent batch size")
        return single_embeddings[0]

    @staticmethod
    def _split_text_middle(text: str) -> tuple[str, str]:
        normalized = str(text or "")
        if len(normalized) < 2:
            return normalized, ""
        mid = len(normalized) // 2
        left_space = normalized.rfind(" ", 0, mid)
        right_space = normalized.find(" ", mid)
        if left_space == -1 and right_space == -1:
            split_idx = mid
        elif left_space == -1:
            split_idx = right_space
        elif right_space == -1:
            split_idx = left_space
        else:
            split_idx = left_space if (mid - left_space) <= (right_space - mid) else right_space
        split_idx = max(1, min(len(normalized) - 1, split_idx))
        left = normalized[:split_idx].strip()
        right = normalized[split_idx:].strip()
        return left, right

    @staticmethod
    def _weighted_average_embeddings(embeddings: list[list[float]], weights: list[int]) -> list[float]:
        if not embeddings:
            raise RuntimeError("Embedding average received empty vectors")
        if len(embeddings) != len(weights):
            raise RuntimeError("Embedding average received mismatched vectors and weights")
        dim = len(embeddings[0])
        if dim == 0:
            raise RuntimeError("Embedding average received empty embedding vector")
        for emb in embeddings:
            if len(emb) != dim:
                raise RuntimeError("Embedding average received vectors with inconsistent dimensions")
        total_weight = float(sum(max(1, int(w)) for w in weights))
        out = [0.0] * dim
        for emb, raw_weight in zip(embeddings, weights):
            weight = float(max(1, int(raw_weight)))
            for i, value in enumerate(emb):
                out[i] += float(value) * weight
        return [value / total_weight for value in out]

    async def _post_with_retry_with_optional_api_key(
        self,
        url: str,
        payload: dict,
        api_key: str | None = None,
        verify: bool | str | None = None,
    ) -> dict:
        # Backward-compatible shim for tests that monkeypatch `_post_with_retry`.
        post_with_retry = self._post_with_retry
        signature = inspect.signature(post_with_retry)
        kwargs: dict[str, Any] = {}
        if "api_key" in signature.parameters:
            kwargs["api_key"] = api_key
        if "verify" in signature.parameters and verify is not None:
            kwargs["verify"] = verify
        return await post_with_retry(url, payload, **kwargs)  # type: ignore[misc]

    def _embedding_verify(self) -> bool | str:
        return self.embedding_ca_bundle_path or True

    @staticmethod
    def _oauth_cache_key(raw_key: str, oauth_url: str, scope: str) -> str:
        payload = f"{oauth_url}|{scope}|{raw_key}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _oauth_expiry_epoch(data: dict[str, Any], fallback_s: int = 1500) -> float:
        raw_exp = data.get("expires_at")
        now = time.time()
        try:
            exp = float(raw_exp)
            if exp > 10_000_000_000:  # milliseconds
                exp = exp / 1000.0
            if exp > now:
                return exp
        except Exception:
            pass
        return now + fallback_s

    async def _resolve_non_openrouter_embedding_key(self) -> str:
        raw_key = (self.embedding_api_key or self.api_key or "").strip()
        if not raw_key:
            raise RuntimeError("Embedding provider API key is not configured")

        oauth_url = self.embedding_oauth_url
        if not oauth_url:
            return raw_key
        cache_key = self._oauth_cache_key(raw_key, oauth_url, self.embedding_oauth_scope)
        now = time.time()
        cached = _EMBEDDING_OAUTH_CACHE.get(cache_key)
        if cached and (cached[1] - now) > 60:
            return cached[0]
        lock = _EMBEDDING_OAUTH_LOCKS.setdefault(cache_key, asyncio.Lock())
        async with lock:
            now = time.time()
            cached = _EMBEDDING_OAUTH_CACHE.get(cache_key)
            if cached and (cached[1] - now) > 60:
                return cached[0]
            auth_header = raw_key if raw_key.lower().startswith("basic ") else f"Basic {raw_key}"
            payload = {"scope": self.embedding_oauth_scope}
            allowed_ips = await self._guard_provider_host(oauth_url)
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s, verify=self._embedding_verify()) as client:
                    resp = await client.post(
                        oauth_url,
                        headers={
                            "Authorization": auth_header,
                            "RqUID": str(uuid.uuid4()),
                            "Accept": "application/json",
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        data=payload,
                    )
                    self._assert_peer_ip(resp, allowed_ips)
                    if resp.status_code >= 400:
                        logger.warning(
                            "Embedding OAuth failed status=%s endpoint=%s body_preview=<suppressed>",
                            resp.status_code,
                            urlparse(oauth_url).path,
                        )
                        resp.raise_for_status()
                    data = resp.json()
            except Exception as exc:
                logger.warning("Embedding OAuth exchange failed; using raw embedding credential: %s", str(exc)[:240])
                return raw_key

            access_token = str(data.get("access_token") or "").strip()
            if not access_token:
                logger.warning("Embedding OAuth exchange returned empty access_token; using raw embedding credential")
                return raw_key
            _EMBEDDING_OAUTH_CACHE[cache_key] = (access_token, self._oauth_expiry_epoch(data))
            return access_token

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

    async def _post_with_retry(
        self,
        url: str,
        payload: dict,
        api_key: str | None = None,
        verify: bool | str | None = None,
    ) -> dict:
        effective_api_key = str(api_key or self.api_key or "").strip()
        if not effective_api_key:
            raise RuntimeError("Provider API key is not configured")
        delay = 0.5
        for attempt in range(self.max_retries + 1):
            try:
                allowed_ips = await self._guard_provider_host(url)
                client_verify = verify if verify is not None else True
                async with httpx.AsyncClient(timeout=self.timeout_s, verify=client_verify) as client:
                    resp = await client.post(url, headers=self._headers_for_api_key(effective_api_key), json=payload)
                    self._assert_peer_ip(resp, allowed_ips)
                    if resp.status_code >= 400:
                        headers = self._provider_error_headers(resp)
                        endpoint = urlparse(url).path
                        is_embedding_endpoint = endpoint.endswith("/embeddings")
                        if is_embedding_endpoint:
                            body_preview = "<suppressed>"
                        else:
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
            except Exception as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    status_code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
                    # Client errors are usually deterministic; retry only explicit rate-limiting.
                    if 400 <= status_code < 500 and status_code != 429:
                        raise
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("Provider retry loop failed")
