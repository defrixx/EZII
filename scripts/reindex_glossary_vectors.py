import argparse
import os
from collections import defaultdict
import hashlib
import math

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet, InvalidToken


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


DATABASE_URL = env("DATABASE_URL", "postgresql+psycopg2://app:app@postgres:5432/app")
QDRANT_URL = env("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = env("QDRANT_COLLECTION", "glossary_entries")
DEFAULT_BASE_URL = env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_API_KEY = env("OPENROUTER_API_KEY", "")
DEFAULT_EMBED_MODEL = env("OPENROUTER_EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_TIMEOUT_S = int(env("PROVIDER_TIMEOUT_S", "30"))
BATCH_SIZE = int(env("REINDEX_BATCH_SIZE", "20"))
VECTOR_SIZE = int(env("REINDEX_VECTOR_SIZE", "1536"))
ENC_PREFIX = "enc:v1:"

engine = create_engine(DATABASE_URL)


def chunks(items: list[dict], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def provider_for_tenant(db: Session, tenant_id: str) -> dict:
    row = db.execute(
        text(
            """
            SELECT base_url, api_key, embedding_model, timeout_s
            FROM provider_settings
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().first()

    if row:
        return {
            "base_url": row["base_url"] or DEFAULT_BASE_URL,
            "api_key": resolve_provider_api_key(str(row["api_key"] or DEFAULT_API_KEY)),
            "embedding_model": row["embedding_model"] or DEFAULT_EMBED_MODEL,
            "timeout_s": row["timeout_s"] or DEFAULT_TIMEOUT_S,
        }
    return {
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "embedding_model": DEFAULT_EMBED_MODEL,
        "timeout_s": DEFAULT_TIMEOUT_S,
    }


def resolve_provider_api_key(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    if not value.startswith(ENC_PREFIX):
        return value
    key = (env("PROVIDER_API_KEY_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        raise RuntimeError(
            "Encrypted provider API key found but PROVIDER_API_KEY_ENCRYPTION_KEY is not configured"
        )
    try:
        token = value[len(ENC_PREFIX) :]
        return Fernet(key.encode("utf-8")).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt provider API key") from exc


def fetch_embeddings(config: dict, inputs: list[str]) -> list[list[float]]:
    if not config["api_key"]:
        return [stub_embedding(text, VECTOR_SIZE) for text in inputs]

    url = f"{config['base_url'].rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {"model": config["embedding_model"], "input": inputs}

    with httpx.Client(timeout=config["timeout_s"]) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json().get("data", [])

    vectors: list[list[float]] = []
    for item in data:
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if isinstance(embedding, list):
            vectors.append(embedding)
    return vectors


def stub_embedding(text: str, size: int = 1536) -> list[float]:
    # Deterministic local fallback for non-production reindex runs.
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = bytearray()
    current = seed
    while len(raw) < size:
        raw.extend(current)
        current = hashlib.sha256(current).digest()
    vals = [((b / 255.0) * 2.0 - 1.0) for b in raw[:size]]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def reindex(tenant_id: str | None = None) -> None:
    qdrant = QdrantClient(url=QDRANT_URL)

    with Session(engine) as db:
        params = {}
        where = ""
        if tenant_id:
            where = "WHERE ge.tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id

        rows = db.execute(
            text(
                f"""
                SELECT
                    ge.id,
                    ge.tenant_id,
                    ge.term,
                    ge.definition,
                    ge.priority AS entry_priority,
                    ge.glossary_id,
                    g.name AS glossary_name,
                    g.priority AS glossary_priority
                FROM glossary_entries ge
                JOIN glossaries g ON g.id = ge.glossary_id
                {where}
                ORDER BY ge.tenant_id, ge.created_at
                """
            ),
            params,
        ).mappings().all()

        by_tenant: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_tenant[str(row["tenant_id"])].append(dict(row))

        total = 0
        for t_id, entries in by_tenant.items():
            cfg = provider_for_tenant(db, t_id)
            if not cfg["api_key"]:
                print(f"Tenant {t_id}: using stub embeddings (no provider key)")

            print(f"Tenant {t_id}: {len(entries)} entries")
            for batch in chunks(entries, BATCH_SIZE):
                inputs = [f"{x['term']}\n{x['definition']}" for x in batch]
                vectors = fetch_embeddings(cfg, inputs)
                if len(vectors) != len(batch):
                    print(f"Skip batch for tenant {t_id}: embedding size mismatch")
                    continue

                points = []
                for item, vector in zip(batch, vectors):
                    points.append(
                        PointStruct(
                            id=str(item["id"]),
                            vector=vector,
                            payload={
                                "tenant_id": str(item["tenant_id"]),
                                "term": item["term"],
                                "definition": item["definition"],
                                "glossary_id": str(item["glossary_id"]),
                                "glossary_name": item["glossary_name"],
                                "glossary_priority": int(item["glossary_priority"]),
                                "entry_priority": int(item["entry_priority"]),
                            },
                        )
                    )

                qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points, wait=True)
                total += len(points)

        print(f"Reindexed vectors: {total}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reindex glossary vectors in Qdrant")
    parser.add_argument("--tenant-id", help="Reindex only one tenant", default=None)
    args = parser.parse_args()
    reindex(args.tenant_id)


if __name__ == "__main__":
    main()
