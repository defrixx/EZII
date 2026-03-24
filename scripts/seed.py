import os
import uuid
from datetime import UTC, datetime

from psycopg2.extras import Json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


DB_URL = env("DATABASE_URL", "postgresql+psycopg2://app:app@postgres:5432/app")
TENANT_ID = env("SEED_TENANT_ID", "00000000-0000-0000-0000-000000000001")
TENANT_NAME = env("SEED_TENANT_NAME", "default-tenant")
ADMIN_ID = env("SEED_ADMIN_ID", "00000000-0000-0000-0000-000000000002")
USER_ID = env("SEED_USER_ID", "00000000-0000-0000-0000-000000000003")
ADMIN_EMAIL = env("SEED_ADMIN_EMAIL", "admin@example.com")
USER_EMAIL = env("SEED_USER_EMAIL", "user@example.com")
PROVIDER_BASE_URL = env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
PROVIDER_API_KEY = env("OPENROUTER_API_KEY", "replace-me")
PROVIDER_MODEL = env("OPENROUTER_MODEL", "openai/gpt-4o-mini")
PROVIDER_EMBED_MODEL = env("OPENROUTER_EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_GLOSSARY_ID = env("SEED_DEFAULT_GLOSSARY_ID", "00000000-0000-0000-0000-000000000004")

engine = create_engine(DB_URL)


def now_utc() -> datetime:
    return datetime.now(UTC)

entries = [
    {
        "term": "Approved source",
        "definition": "Одобренный источник знаний, который разрешено использовать в retrieval и ответах ассистента.",
        "example": "Перед публикацией новый документ переводят в approved source.",
        "synonyms": ["одобренный источник", "approved content"],
        "forbidden": ["непроверенный внешний источник"],
        "domain": "knowledge-base",
    },
    {
        "term": "Регламент",
        "definition": "Внутренний нормативный документ, который задает порядок действий, правила согласования и критерии контроля.",
        "example": "Ответ по процессу закупки должен ссылаться на действующий регламент.",
        "synonyms": ["процедура", "policy"],
        "forbidden": ["устная договоренность без фиксации"],
        "domain": "operations",
    },
    {
        "term": "Внутренний термин",
        "definition": "Рабочее понятие из базы знаний, которое должно использоваться в согласованной форме во всех ответах.",
        "example": "Ассистент подставляет внутренний термин из глоссария вместо свободной формулировки.",
        "synonyms": ["стандартизированный термин", "business term"],
        "forbidden": ["неутвержденный синоним"],
        "domain": "glossary",
    },
]

allow_domains = [
    "docs.python.org",
    "fastapi.tiangolo.com",
    "docs.sqlalchemy.org",
    "qdrant.tech",
    "www.postgresql.org",
    "developer.mozilla.org",
]

with Session(engine) as db:
    tenant_preexisting = bool(
        db.execute(
            text(
                """
            SELECT 1
            FROM tenants
            WHERE id = :tenant_id
        """
            ),
            {"tenant_id": TENANT_ID},
        ).scalar()
    )

    db.execute(
        text(
            """
        INSERT INTO tenants (id, name, created_at)
        VALUES (:id, :name, :created_at)
        ON CONFLICT (id) DO NOTHING
    """
        ),
        {"id": TENANT_ID, "name": TENANT_NAME, "created_at": now_utc()},
    )

    for uid, email, role in [
        (ADMIN_ID, ADMIN_EMAIL, "admin"),
        (USER_ID, USER_EMAIL, "user"),
    ]:
        db.execute(
            text(
                """
            INSERT INTO users (id, tenant_id, email, role, created_at)
            VALUES (:id, :tenant_id, :email, :role, :created_at)
            ON CONFLICT (tenant_id, email) DO UPDATE SET
              role = EXCLUDED.role
        """
            ),
            {
                "id": uid,
                "tenant_id": TENANT_ID,
                "email": email,
                "role": role,
                "created_at": now_utc(),
            },
        )

    if not tenant_preexisting:
        db.execute(
            text(
                """
            INSERT INTO provider_settings
            (id, tenant_id, base_url, api_key, model_name, embedding_model, timeout_s, retry_policy, knowledge_mode, empty_retrieval_mode, strict_glossary_mode, web_enabled, show_confidence, show_source_tags, response_tone, updated_at)
            VALUES
            (:id, :tenant_id, :base_url, :api_key, :model_name, :embedding_model, 30, 2, 'glossary_documents_web', 'model_only_fallback', false, true, false, true, :response_tone, :updated_at)
            ON CONFLICT (tenant_id) DO NOTHING
        """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": TENANT_ID,
                "base_url": PROVIDER_BASE_URL,
                "api_key": PROVIDER_API_KEY,
                "model_name": PROVIDER_MODEL,
                "embedding_model": PROVIDER_EMBED_MODEL,
                "response_tone": "consultative_supportive",
                "updated_at": now_utc(),
            },
        )

        db.execute(
            text(
                """
            INSERT INTO glossaries
            (id, tenant_id, name, description, priority, enabled, is_default, created_at, updated_at)
            VALUES
            (:id, :tenant_id, :name, :description, :priority, :enabled, :is_default, :created_at, :updated_at)
            ON CONFLICT (tenant_id, name) DO NOTHING
        """
            ),
            {
                "id": DEFAULT_GLOSSARY_ID,
                "tenant_id": TENANT_ID,
                "name": "Default",
                "description": "Default knowledge glossary",
                "priority": 100,
                "enabled": True,
                "is_default": True,
                "created_at": now_utc(),
                "updated_at": now_utc(),
            },
        )

        default_glossary_id = db.execute(
            text(
                """
            SELECT id
            FROM glossaries
            WHERE tenant_id = :tenant_id
              AND name = :name
        """
            ),
            {"tenant_id": TENANT_ID, "name": "Default"},
        ).scalar_one()

        for e in entries:
            db.execute(
                text(
                    """
                INSERT INTO glossary_entries
                (id, tenant_id, glossary_id, term, definition, example, synonyms, forbidden_interpretations, owner, version, priority, status, created_at, updated_at, created_by, metadata_json)
                SELECT
                :id, :tenant_id, :glossary_id, :term, :definition, :example, :synonyms, :forbidden, :owner, 1, 10, 'active', :created_at, :updated_at, :created_by, :metadata
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM glossary_entries
                    WHERE tenant_id = :tenant_id
                      AND glossary_id = :glossary_id
                      AND term = :term
                      AND definition = :definition
                )
            """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": TENANT_ID,
                    "glossary_id": default_glossary_id,
                    "term": e["term"],
                    "definition": e["definition"],
                    "example": e["example"],
                    "synonyms": e["synonyms"],
                    "forbidden": e["forbidden"],
                    "owner": "knowledge-base-team",
                    "created_at": now_utc(),
                    "updated_at": now_utc(),
                    "created_by": ADMIN_ID,
                    "metadata": Json({"domain": e["domain"]}),
                },
            )

        for d in allow_domains:
            db.execute(
                text(
                    """
                INSERT INTO allowlist_domains (id, tenant_id, domain, enabled, created_at)
                VALUES (:id, :tenant_id, :domain, true, :created_at)
                ON CONFLICT (tenant_id, domain) DO NOTHING
            """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": TENANT_ID,
                    "domain": d,
                    "created_at": now_utc(),
                },
            )

    db.commit()

print("Seed completed")
