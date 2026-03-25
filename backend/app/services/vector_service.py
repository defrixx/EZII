import time
from typing import Any, Callable

from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, PointStruct


class VectorStoreError(RuntimeError):
    pass


class VectorService:
    def __init__(
        self,
        url: str,
        collection: str,
        *,
        timeout_s: float = 3.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.2,
    ):
        self.client = QdrantClient(url=url, timeout=timeout_s)
        self.collection = collection
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_s = max(0.0, float(retry_backoff_s))

    def _call_with_retry(self, operation: str, fn: Callable[[], Any]) -> Any:
        attempts = max(0, int(getattr(self, "max_retries", 0))) + 1
        backoff = max(0.0, float(getattr(self, "retry_backoff_s", 0.0)))
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                if backoff > 0:
                    time.sleep(min(backoff * (2 ** (attempt - 1)), 2.0))
        assert last_exc is not None
        raise VectorStoreError(f"Qdrant {operation} failed") from last_exc

    def upsert_entry(self, entry_id: str, tenant_id: str, vector: list[float], payload: dict) -> None:
        point = PointStruct(id=entry_id, vector=vector, payload={"tenant_id": tenant_id, **payload})
        self._call_with_retry(
            "upsert_entry",
            lambda: self.client.upsert(collection_name=self.collection, points=[point], wait=True),
        )

    def upsert_entries(self, entries: list[dict]) -> None:
        if not entries:
            return
        points = [
            PointStruct(
                id=entry["id"],
                vector=entry["vector"],
                payload=entry["payload"],
            )
            for entry in entries
        ]
        self._call_with_retry(
            "upsert_entries",
            lambda: self.client.upsert(collection_name=self.collection, points=points, wait=True),
        )

    def _build_filter(self, tenant_id: str, filters: dict[str, str | bool | int] | None = None) -> Filter:
        must = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id),
            )
        ]
        for key, value in (filters or {}).items():
            must.append(
                FieldCondition(
                    key=key,
                    match=MatchValue(value=value),
                )
            )
        return Filter(must=must)

    def search(
        self,
        tenant_id: str,
        vector: list[float],
        limit: int = 5,
        glossary_ids: list[str] | None = None,
        filters: dict[str, str | bool | int] | None = None,
    ) -> list[dict]:
        query_limit = limit * 4 if glossary_ids else limit
        results = self._call_with_retry(
            "search",
            lambda: self.client.search(
                collection_name=self.collection,
                query_vector=vector,
                limit=query_limit,
                query_filter=self._build_filter(tenant_id, filters),
            ),
        )
        rows = [
            {
                "id": str(r.id),
                "score": float(r.score),
                "payload": r.payload or {},
            }
            for r in results
        ]
        if glossary_ids:
            allowed = set(glossary_ids)
            rows = [row for row in rows if str(row["payload"].get("glossary_id", "")) in allowed]
        return rows[:limit]

    def delete_entry(self, entry_id: str, *, tenant_id: str) -> None:
        records = self._call_with_retry(
            "retrieve",
            lambda: self.client.retrieve(
                collection_name=self.collection,
                ids=[entry_id],
                with_payload=True,
            ),
        )
        if not records:
            return
        payload = records[0].payload or {}
        if str(payload.get("tenant_id") or "") != str(tenant_id):
            return
        self._call_with_retry(
            "delete_entry",
            lambda: self.client.delete(
                collection_name=self.collection,
                points_selector=[entry_id],
                wait=True,
            ),
        )

    def delete_by_field(self, field: str, value: str, tenant_id: str | None = None) -> None:
        must = [
            FieldCondition(
                key=field,
                match=MatchValue(value=value),
            )
        ]
        if tenant_id:
            must.append(
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=tenant_id),
                )
            )
        self._call_with_retry(
            "delete_by_field",
            lambda: self.client.delete(
                collection_name=self.collection,
                points_selector=Filter(
                    must=must
                ),
                wait=True,
            ),
        )

    def delete_by_filters(
        self,
        *,
        tenant_id: str,
        must: dict[str, str | bool | int] | None = None,
        must_not: dict[str, str | bool | int] | None = None,
    ) -> None:
        must_conditions = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=tenant_id),
            )
        ]
        for key, value in (must or {}).items():
            must_conditions.append(
                FieldCondition(
                    key=key,
                    match=MatchValue(value=value),
                )
            )
        must_not_conditions = []
        for key, value in (must_not or {}).items():
            must_not_conditions.append(
                FieldCondition(
                    key=key,
                    match=MatchValue(value=value),
                )
            )
        self._call_with_retry(
            "delete_by_filters",
            lambda: self.client.delete(
                collection_name=self.collection,
                points_selector=Filter(
                    must=must_conditions,
                    must_not=must_not_conditions or None,
                ),
                wait=True,
            ),
        )
