import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    func,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id_id"),
        CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
    )


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="New chat", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_chats_tenant_id_id"),
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_types: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "chat_id"],
            ["chats.tenant_id", "chats.id"],
            name="fk_messages_tenant_chat",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_messages_tenant_user",
        ),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )


class Glossary(Base):
    __tablename__ = "glossaries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_glossary_tenant_name"),
        Index(
            "uq_glossary_single_default_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=is_default.is_(True),
        ),
    )


class GlossaryEntry(Base):
    __tablename__ = "glossary_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    glossary_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("glossaries.id"), nullable=False, index=True)
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    example: Mapped[str | None] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    forbidden_interpretations: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (
        CheckConstraint("status IN ('active', 'draft', 'disabled', 'archived')", name="ck_glossary_entries_status"),
        Index(
            "uq_glossary_entries_tenant_glossary_term_ci",
            "tenant_id",
            "glossary_id",
            func.lower(term),
            unique=True,
        ),
    )


class ProviderSetting(Base):
    __tablename__ = "provider_settings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True, unique=True)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    timeout_s: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    retry_policy: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    knowledge_mode: Mapped[str] = mapped_column(String(50), default="glossary_documents", nullable=False)
    empty_retrieval_mode: Mapped[str] = mapped_column(String(50), default="model_only_fallback", nullable=False)
    strict_glossary_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    show_confidence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    show_source_tags: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    response_tone: Mapped[str] = mapped_column(String(50), default="consultative_supportive", nullable=False)
    max_user_messages_total: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    chat_context_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    history_user_turn_limit: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    history_message_limit: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    history_token_budget: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    rewrite_history_message_limit: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "knowledge_mode IN ('glossary_only', 'glossary_documents', 'glossary_documents_web')",
            name="ck_provider_settings_knowledge_mode",
        ),
        CheckConstraint(
            "empty_retrieval_mode IN ('strict_fallback', 'model_only_fallback', 'clarifying_fallback')",
            name="ck_provider_settings_empty_retrieval_mode",
        ),
        CheckConstraint(
            "response_tone IN ('consultative_supportive', 'neutral_reference')",
            name="ck_provider_settings_response_tone",
        ),
    )


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False, index=True)
    enabled_in_retrieval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_documents_tenant_id_id"),
        CheckConstraint("source_type IN ('upload', 'website_snapshot')", name="ck_documents_source_type"),
        CheckConstraint("status IN ('draft', 'processing', 'approved', 'archived', 'failed')", name="ck_documents_status"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_chunks_tenant_document",
        ),
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )


class DocumentIngestionJob(Base):
    __tablename__ = "document_ingestion_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    triggered_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name="fk_document_jobs_tenant_document",
        ),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_document_ingestion_jobs_status"),
    )


class StorageCleanupTask(Base):
    __tablename__ = "storage_cleanup_tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "storage_path", name="uq_storage_cleanup_task_tenant_path"),
        CheckConstraint("status IN ('pending', 'running', 'failed')", name="ck_storage_cleanup_tasks_status"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ErrorLog(Base):
    __tablename__ = "error_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    chat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id"), nullable=True)
    error_type: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ResponseTrace(Base):
    __tablename__ = "response_traces"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    knowledge_mode: Mapped[str] = mapped_column(String(50), default="glossary_documents", nullable=False)
    answer_mode: Mapped[str] = mapped_column(String(50), default="grounded", nullable=False)
    source_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    glossary_entries_used: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    document_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    web_snapshot_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    web_domains_used: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    ranking_scores: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    token_usage: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "knowledge_mode IN ('glossary_only', 'glossary_documents', 'glossary_documents_web')",
            name="ck_response_traces_knowledge_mode",
        ),
        CheckConstraint(
            "answer_mode IN ('grounded', 'strict_fallback', 'model_only', 'clarifying', 'error')",
            name="ck_response_traces_answer_mode",
        ),
    )
