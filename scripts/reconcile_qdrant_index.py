import argparse
import hashlib
import os
from collections import defaultdict

import httpx
from cryptography.fernet import Fernet, InvalidToken
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


DATABASE_URL = env("DATABASE_URL", "postgresql+psycopg2://app:app@postgres:5432/app")
QDRANT_URL = env("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = env("QDRANT_COLLECTION", "glossary_entries")
DEFAULT_BASE_URL = env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_API_KEY = env("OPENROUTER_API_KEY", "")
DEFAULT_EMBED_MODEL = env("OPENROUTER_EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_TIMEOUT_S = int(env("PROVIDER_TIMEOUT_S", "30"))
VECTOR_SIZE = int(env("REINDEX_VECTOR_SIZE", "1536"))
BATCH_SIZE = int(env("REINDEX_BATCH_SIZE", "20"))
ENC_PREFIX = "enc:v1:"


engine = create_engine(DATABASE_URL)


def chunks(items: list[dict], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def payload_hash(payload: dict) -> str:
    basis = "|".join(
        [
            str(payload.get("term", "")),
            str(payload.get("definition", "")),
            str(payload.get("glossary_id", "")),
            str(payload.get("glossary_name", "")),
            str(payload.get("glossary_priority", "")),
            str(payload.get("entry_priority", "")),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


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


def stub_embedding(text: str, size: int = 1536) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = bytearray()
    current = seed
    while len(raw) < size:
        raw.extend(current)
        current = hashlib.sha256(current).digest()
    values = [((b / 255.0) * 2.0 - 1.0) for b in raw[:size]]
    norm = sum(v * v for v in values) ** 0.5 or 1.0
    return [v / norm for v in values]


def fetch_embeddings(config: dict, inputs: list[str]) -> list[list[float]]:
    if not config["api_key"]:
        return [stub_embedding(x, VECTOR_SIZE) for x in inputs]

    url = f"{config['base_url'].rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}
    payload = {"model": config["embedding_model"], "input": inputs}
    with httpx.Client(timeout=config["timeout_s"]) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    return [x["embedding"] for x in data if isinstance(x, dict) and isinstance(x.get("embedding"), list)]


def load_db_rows(db: Session, tenant_id: str | None) -> list[dict]:
    where = ""
    params: dict[str, str] = {}
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
              ge.status,
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
    return [dict(r) for r in rows]


def load_qdrant_points(qdrant: QdrantClient, tenant_id: str | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    offset = None
    while True:
        points, offset = qdrant.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=256,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        for p in points:
            payload = p.payload or {}
            p_tenant = str(payload.get("tenant_id", ""))
            if tenant_id and p_tenant != tenant_id:
                continue
            out[str(p.id)] = {"id": str(p.id), "tenant_id": p_tenant, "payload": payload}
        if offset is None:
            break
    return out


def reconcile(tenant_id: str | None, apply_changes: bool) -> None:
    qdrant = QdrantClient(url=QDRANT_URL)
    with Session(engine) as db:
        rows = load_db_rows(db, tenant_id)
        db_map: dict[str, dict] = {}
        by_tenant: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            entry_id = str(row["id"])
            payload = {
                "tenant_id": str(row["tenant_id"]),
                "term": row["term"],
                "definition": row["definition"],
                "glossary_id": str(row["glossary_id"]),
                "glossary_name": row["glossary_name"],
                "glossary_priority": int(row["glossary_priority"]),
                "entry_priority": int(row["entry_priority"]),
            }
            db_map[entry_id] = {
                "id": entry_id,
                "tenant_id": str(row["tenant_id"]),
                "status": str(row["status"]),
                "payload": payload,
                "hash": payload_hash(payload),
                "text": f"{row['term']}\n{row['definition']}",
            }
            by_tenant[str(row["tenant_id"])].append(db_map[entry_id])

        q_map = load_qdrant_points(qdrant, tenant_id)
        q_ids = set(q_map.keys())
        db_ids = set(db_map.keys())

        stale_ids = sorted(q_ids - db_ids)
        to_upsert: dict[str, list[dict]] = defaultdict(list)

        for entry_id in sorted(db_ids):
            row = db_map[entry_id]
            if row["status"] != "active":
                if entry_id in q_map:
                    stale_ids.append(entry_id)
                continue
            q_row = q_map.get(entry_id)
            if not q_row:
                to_upsert[row["tenant_id"]].append(row)
                continue
            q_payload = q_row["payload"] or {}
            if payload_hash({**row["payload"]}) != payload_hash(
                {
                    "term": q_payload.get("term", ""),
                    "definition": q_payload.get("definition", ""),
                    "glossary_id": str(q_payload.get("glossary_id", "")),
                    "glossary_name": q_payload.get("glossary_name", ""),
                    "glossary_priority": int(q_payload.get("glossary_priority", 0) or 0),
                    "entry_priority": int(q_payload.get("entry_priority", 0) or 0),
                }
            ):
                to_upsert[row["tenant_id"]].append(row)

        print(f"DB rows: {len(db_ids)}")
        print(f"Qdrant rows: {len(q_ids)}")
        print(f"Stale vectors to delete: {len(stale_ids)}")
        print(f"Entries to upsert: {sum(len(v) for v in to_upsert.values())}")
        if not apply_changes:
            print("Dry-run mode: no changes applied")
            return

        if stale_ids:
            qdrant.delete(collection_name=QDRANT_COLLECTION, points_selector=stale_ids, wait=True)

        for t_id, entries in to_upsert.items():
            cfg = provider_for_tenant(db, t_id)
            if not cfg["api_key"]:
                print(f"Tenant {t_id}: using stub embeddings")
            for batch in chunks(entries, BATCH_SIZE):
                embeddings = fetch_embeddings(cfg, [x["text"] for x in batch])
                if len(embeddings) != len(batch):
                    print(f"Tenant {t_id}: embedding size mismatch, skipped {len(batch)} entries")
                    continue
                points = []
                for row, emb in zip(batch, embeddings):
                    points.append(PointStruct(id=row["id"], vector=emb, payload=row["payload"]))
                qdrant.upsert(collection_name=QDRANT_COLLECTION, points=points, wait=True)

        print("Reconciliation complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile Postgres glossary entries with Qdrant index")
    parser.add_argument("--tenant-id", default=None, help="Limit to one tenant")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Without this flag script runs dry-run")
    args = parser.parse_args()
    reconcile(tenant_id=args.tenant_id, apply_changes=args.apply)


if __name__ == "__main__":
    main()
