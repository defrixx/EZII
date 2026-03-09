from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, PointStruct


class VectorService:
    def __init__(self, url: str, collection: str):
        self.client = QdrantClient(url=url)
        self.collection = collection

    def upsert_entry(self, entry_id: str, tenant_id: str, vector: list[float], payload: dict) -> None:
        point = PointStruct(id=entry_id, vector=vector, payload={"tenant_id": tenant_id, **payload})
        self.client.upsert(collection_name=self.collection, points=[point], wait=True)

    def search(self, tenant_id: str, vector: list[float], limit: int = 5, glossary_ids: list[str] | None = None) -> list[dict]:
        query_limit = limit * 4 if glossary_ids else limit
        results = self.client.search(
            collection_name=self.collection,
            query_vector=vector,
            limit=query_limit,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=tenant_id),
                    )
                ]
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

    def delete_entry(self, entry_id: str) -> None:
        self.client.delete(
            collection_name=self.collection,
            points_selector=[entry_id],
            wait=True,
        )
