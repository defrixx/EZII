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
        "term": "Старшие арканы",
        "definition": "22 ключевые карты Таро, описывающие архетипические этапы пути и внутренние уроки.",
        "example": "Запрос о жизненном этапе часто интерпретируется через старшие арканы.",
        "synonyms": ["major arcana", "22 аркана"],
        "forbidden": ["гарантированное предсказание будущего"],
        "domain": "tarot",
    },
    {
        "term": "Карта рождения",
        "definition": "Астрологическая схема положения планет в момент рождения человека.",
        "example": "Для анализа личных склонностей сначала смотрят карту рождения.",
        "synonyms": ["натальная карта", "natal chart"],
        "forbidden": ["абсолютная детерминация судьбы"],
        "domain": "astrology",
    },
    {
        "term": "Число жизненного пути",
        "definition": "Базовый нумерологический показатель, вычисляемый по дате рождения.",
        "example": "Число жизненного пути используют как ориентир личных сильных сторон.",
        "synonyms": ["life path number"],
        "forbidden": ["научно доказанная причинность"],
        "domain": "numerology",
    },
]

allow_domains = [
    "biddytarot.com",
    "labyrinthos.co",
    "astro.com",
    "cafeastrology.com",
    "numerologist.com",
    "worldnumerology.com",
]

with Session(engine) as db:
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
            ON CONFLICT (id) DO NOTHING
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

    db.execute(
        text(
            """
        INSERT INTO provider_settings
        (id, tenant_id, base_url, api_key, model_name, embedding_model, timeout_s, retry_policy, strict_glossary_mode, web_enabled, show_confidence, show_source_tags, response_tone, updated_at)
        VALUES
        (:id, :tenant_id, :base_url, :api_key, :model_name, :embedding_model, 30, 2, false, true, false, true, :response_tone, :updated_at)
        ON CONFLICT (tenant_id) DO UPDATE SET
          base_url = EXCLUDED.base_url,
          api_key = EXCLUDED.api_key,
          model_name = EXCLUDED.model_name,
          embedding_model = EXCLUDED.embedding_model,
          strict_glossary_mode = EXCLUDED.strict_glossary_mode,
          web_enabled = EXCLUDED.web_enabled,
          show_confidence = EXCLUDED.show_confidence,
          show_source_tags = EXCLUDED.show_source_tags,
          response_tone = EXCLUDED.response_tone,
          updated_at = EXCLUDED.updated_at
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
        ON CONFLICT (id) DO NOTHING
    """
        ),
        {
            "id": DEFAULT_GLOSSARY_ID,
            "tenant_id": TENANT_ID,
            "name": "Default",
            "description": "Seed default glossary",
            "priority": 100,
            "enabled": True,
            "is_default": True,
            "created_at": now_utc(),
            "updated_at": now_utc(),
        },
    )

    for e in entries:
        db.execute(
            text(
                """
            INSERT INTO glossary_entries
            (id, tenant_id, glossary_id, term, definition, example, synonyms, forbidden_interpretations, owner, version, priority, status, created_at, updated_at, created_by, metadata_json)
            VALUES
            (:id, :tenant_id, :glossary_id, :term, :definition, :example, :synonyms, :forbidden, :owner, 1, 10, 'active', :created_at, :updated_at, :created_by, :metadata)
            ON CONFLICT (id) DO NOTHING
        """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": TENANT_ID,
                "glossary_id": DEFAULT_GLOSSARY_ID,
                "term": e["term"],
                "definition": e["definition"],
                "example": e["example"],
                "synonyms": e["synonyms"],
                "forbidden": e["forbidden"],
                "owner": "esoteric-content-team",
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
