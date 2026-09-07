import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

def utcnow(): return datetime.now(timezone.utc)

class ModelConnection(Base):
    __tablename__="model_connections"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    name: Mapped[str]=mapped_column(String(255),unique=True,nullable=False)
    kind: Mapped[str]=mapped_column(String(32),nullable=False)
    base_url: Mapped[str]=mapped_column(String(1024),nullable=False)
    api_key: Mapped[str|None]=mapped_column(String(2048))
    timeout_s: Mapped[int]=mapped_column(Integer,default=30,nullable=False)
    retry_count: Mapped[int]=mapped_column(Integer,default=2,nullable=False)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(CheckConstraint("kind IN ('openrouter','lm_studio','openai_compatible')"),)

class ModelEndpoint(Base):
    __tablename__="model_endpoints"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("model_connections.id",ondelete="CASCADE"),nullable=False,index=True)
    name: Mapped[str]=mapped_column(String(255),nullable=False)
    model_id: Mapped[str]=mapped_column(String(255),nullable=False)
    capability: Mapped[str]=mapped_column(String(16),nullable=False)
    vector_size: Mapped[int|None]=mapped_column(Integer)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(UniqueConstraint("connection_id","model_id","capability"),CheckConstraint("capability IN ('chat','embedding')"),CheckConstraint("capability != 'embedding' OR vector_size IS NOT NULL"))

class KnowledgeBase(Base):
    __tablename__="knowledge_bases"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    name: Mapped[str]=mapped_column(String(255),nullable=False)
    description: Mapped[str|None]=mapped_column(Text)
    system_prompt: Mapped[str|None]=mapped_column(Text)
    chat_model_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("model_endpoints.id",ondelete="SET NULL"))
    embedding_model_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("model_endpoints.id",ondelete="SET NULL"))
    publication_mode: Mapped[str]=mapped_column(String(16),default="manual",nullable=False)
    knowledge_mode: Mapped[list[str]]=mapped_column(ARRAY(String),default=lambda:["upload","website_snapshot","github_playbook"],nullable=False)
    empty_retrieval_mode: Mapped[str]=mapped_column(String(32),default="clarifying_fallback",nullable=False)
    response_tone: Mapped[str]=mapped_column(String(32),default="neutral",nullable=False)
    chat_context_enabled: Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    history_message_limit: Mapped[int]=mapped_column(Integer,default=12,nullable=False)
    history_token_budget: Mapped[int]=mapped_column(Integer,default=1200,nullable=False)
    context_token_budget: Mapped[int]=mapped_column(Integer,default=4000,nullable=False)
    chunk_size_chars: Mapped[int]=mapped_column(Integer,default=900,nullable=False)
    chunk_overlap_chars: Mapped[int]=mapped_column(Integer,default=250,nullable=False)
    is_default: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    reindex_required: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(Index("uq_kb_name_ci",func.lower(name),unique=True),Index("uq_kb_default","is_default",unique=True,postgresql_where=is_default.is_(True)),CheckConstraint("publication_mode IN ('automatic','manual')"),CheckConstraint("empty_retrieval_mode IN ('strict_fallback','model_only_fallback','clarifying_fallback')"),CheckConstraint("chunk_size_chars BETWEEN 200 AND 8000"),CheckConstraint("chunk_overlap_chars >= 0 AND chunk_overlap_chars < chunk_size_chars"))

class Chat(Base):
    __tablename__="chats"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),nullable=False,index=True)
    title: Mapped[str]=mapped_column(String(255),default="New chat",nullable=False)
    is_pinned: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    is_archived: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)

class Message(Base):
    __tablename__="messages"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("chats.id",ondelete="CASCADE"),nullable=False,index=True)
    role: Mapped[str]=mapped_column(String(20),nullable=False)
    content: Mapped[str]=mapped_column(Text,nullable=False)
    source_types: Mapped[list[str]|None]=mapped_column(ARRAY(String))
    metadata_json: Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)

class Glossary(Base):
    __tablename__="glossaries"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),nullable=False,index=True)
    name: Mapped[str]=mapped_column(String(255),nullable=False)
    description: Mapped[str|None]=mapped_column(Text)
    priority: Mapped[int]=mapped_column(Integer,default=100,nullable=False)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    is_default: Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(UniqueConstraint("knowledge_base_id","name"),Index("uq_default_glossary_per_kb","knowledge_base_id",unique=True,postgresql_where=is_default.is_(True)))

class GlossaryEntry(Base):
    __tablename__="glossary_entries"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    glossary_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("glossaries.id",ondelete="CASCADE"),nullable=False,index=True)
    term: Mapped[str]=mapped_column(String(255),nullable=False)
    definition: Mapped[str]=mapped_column(Text,nullable=False)
    example: Mapped[str|None]=mapped_column(Text)
    synonyms: Mapped[list[str]]=mapped_column(ARRAY(String),default=list,nullable=False)
    forbidden_interpretations: Mapped[list[str]]=mapped_column(ARRAY(String),default=list,nullable=False)
    priority: Mapped[int]=mapped_column(Integer,default=100,nullable=False)
    status: Mapped[str]=mapped_column(String(32),default="active",nullable=False)
    metadata_json: Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(Index("uq_glossary_term_ci","glossary_id",func.lower(term),unique=True),)

class Document(Base):
    __tablename__="documents"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),nullable=False,index=True)
    title: Mapped[str]=mapped_column(String(255),nullable=False)
    source_type: Mapped[str]=mapped_column(String(32),nullable=False)
    mime_type: Mapped[str|None]=mapped_column(String(255)); file_name: Mapped[str|None]=mapped_column(String(255)); storage_path: Mapped[str|None]=mapped_column(String(1024))
    status: Mapped[str]=mapped_column(String(32),default="draft",nullable=False,index=True)
    enabled_in_retrieval: Mapped[bool]=mapped_column(Boolean,default=True,nullable=False)
    checksum: Mapped[str|None]=mapped_column(String(128)); metadata_json: Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False); approved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    __table_args__=(UniqueConstraint("knowledge_base_id","source_type","checksum","file_name",name="uq_source_content_file"),CheckConstraint("source_type IN ('upload','website_snapshot','github_playbook')"),CheckConstraint("status IN ('draft','processing','ready','approved','archived','failed')"))

class DocumentChunk(Base):
    __tablename__="document_chunks"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    document_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("documents.id",ondelete="CASCADE"),nullable=False,index=True)
    chunk_index: Mapped[int]=mapped_column(Integer,nullable=False); content: Mapped[str]=mapped_column(Text,nullable=False); token_count: Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    embedding_model_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("model_endpoints.id",ondelete="SET NULL")); vector_size: Mapped[int|None]=mapped_column(Integer); metadata_json: Mapped[dict]=mapped_column(JSON,default=dict,nullable=False); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(UniqueConstraint("document_id","chunk_index"),)

class IngestionJob(Base):
    __tablename__="ingestion_jobs"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),nullable=False,index=True)
    document_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("documents.id",ondelete="CASCADE"),index=True)
    kind: Mapped[str]=mapped_column(String(32),nullable=False)
    status: Mapped[str]=mapped_column(String(20),default="processing",nullable=False,index=True)
    attempts: Mapped[int]=mapped_column(Integer,default=1,nullable=False)
    error_code: Mapped[str|None]=mapped_column(String(100))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    __table_args__=(CheckConstraint("status IN ('queued','processing','completed','failed')"),)

class StorageCleanupTask(Base):
    __tablename__="storage_cleanup_tasks"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),nullable=False,index=True)
    document_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),nullable=True)
    storage_path: Mapped[str|None]=mapped_column(String(1024))
    vector_model_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True))
    status: Mapped[str]=mapped_column(String(20),default="pending",nullable=False,index=True)
    attempts: Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    error_code: Mapped[str|None]=mapped_column(String(100))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)

class ResponseTrace(Base):
    __tablename__="response_traces"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("knowledge_bases.id",ondelete="CASCADE"),nullable=False,index=True)
    chat_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("chats.id",ondelete="CASCADE"),nullable=False,index=True)
    model_endpoint_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("model_endpoints.id",ondelete="SET NULL"))
    answer_mode: Mapped[str]=mapped_column(String(32),nullable=False); source_types: Mapped[list[str]]=mapped_column(ARRAY(String),default=list,nullable=False); source_ids: Mapped[list[str]]=mapped_column(ARRAY(String),default=list,nullable=False)
    ranking_scores: Mapped[dict]=mapped_column(JSON,default=dict,nullable=False); token_usage: Mapped[dict]=mapped_column(JSON,default=dict,nullable=False); warning_codes: Mapped[list[str]]=mapped_column(ARRAY(String),default=list,nullable=False); latency_ms: Mapped[float]=mapped_column(Float,default=0,nullable=False); status: Mapped[str]=mapped_column(String(32),nullable=False); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
