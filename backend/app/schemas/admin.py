import json
import ipaddress
import re
import socket
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
KnowledgeMode = Literal["glossary_only", "glossary_documents", "glossary_documents_web"]
EmptyRetrievalMode = Literal["strict_fallback", "model_only_fallback", "clarifying_fallback"]
AnswerMode = Literal["grounded", "strict_fallback", "model_only", "clarifying", "error"]
MAX_DOCUMENT_METADATA_JSON_BYTES = 8192


def _is_public_host(host: str) -> bool:
    lowered = host.strip().lower()
    if not lowered or lowered in BLOCKED_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(lowered)
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        )
    except ValueError:
        pass
    if lowered.endswith(".local"):
        return False
    return bool(DOMAIN_RE.fullmatch(lowered))


def _resolve_public_host(host: str) -> None:
    lowered = host.strip().lower()
    if not _is_public_host(lowered):
        raise ValueError("Host must resolve to public network addresses")
    try:
        infos = socket.getaddrinfo(lowered, None)
    except socket.gaierror as exc:
        raise ValueError("Host must resolve to public network addresses") from exc
    for info in infos:
        raw_ip = info[4][0]
        ip = ipaddress.ip_address(raw_ip)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Host must resolve to public network addresses")


def validate_document_metadata_json(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    if "tags" in payload:
        payload["tags"] = normalize_tags(payload["tags"])
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_METADATA_JSON_BYTES:
        raise ValueError(f"metadata_json exceeds {MAX_DOCUMENT_METADATA_JSON_BYTES} bytes")
    return payload


def normalize_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("tags must be a list of strings")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = str(item or "").strip()
        if not tag:
            continue
        lowered = tag.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(tag)
    return cleaned


class ProviderSettingsIn(BaseModel):
    base_url: AnyHttpUrl
    api_key: str | None = Field(default=None, min_length=16, max_length=1024)
    model_name: str = Field(min_length=2, max_length=255)
    embedding_model: str = Field(min_length=2, max_length=255)
    timeout_s: int = Field(default=30, ge=1, le=120)
    retry_policy: int = Field(default=2, ge=0, le=5)
    knowledge_mode: KnowledgeMode = "glossary_documents"
    empty_retrieval_mode: EmptyRetrievalMode = "model_only_fallback"
    strict_glossary_mode: bool = False
    web_enabled: bool = False
    show_confidence: bool = False
    show_source_tags: bool = True
    response_tone: Literal["consultative_supportive", "neutral_reference"] = "consultative_supportive"
    max_user_messages_total: int = Field(default=5, ge=1, le=10000)
    chat_context_enabled: bool = True
    history_user_turn_limit: int = Field(default=6, ge=1, le=20)
    history_message_limit: int = Field(default=12, ge=1, le=40)
    history_token_budget: int = Field(default=1200, ge=100, le=8000)
    rewrite_history_message_limit: int = Field(default=8, ge=1, le=20)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        parsed = urlparse(str(value))
        host = parsed.hostname or ""
        if parsed.scheme.lower() != "https":
            raise ValueError("base_url must use https")
        _resolve_public_host(host)
        return value


class ProviderSettingsOut(BaseModel):
    id: str
    tenant_id: str
    base_url: str
    api_key: str
    model_name: str
    embedding_model: str
    timeout_s: int
    retry_policy: int
    knowledge_mode: KnowledgeMode
    empty_retrieval_mode: EmptyRetrievalMode
    strict_glossary_mode: bool
    web_enabled: bool
    show_confidence: bool
    show_source_tags: bool
    response_tone: Literal["consultative_supportive", "neutral_reference"]
    max_user_messages_total: int
    chat_context_enabled: bool
    history_user_turn_limit: int
    history_message_limit: int
    history_token_budget: int
    rewrite_history_message_limit: int
    updated_at: datetime


class LogOut(BaseModel):
    id: str
    created_at: datetime
    type: str
    message: str


class TraceOut(BaseModel):
    id: str
    chat_id: str
    model: str
    knowledge_mode: KnowledgeMode
    answer_mode: AnswerMode
    source_types: list[str]
    glossary_entries_used: list[str]
    document_ids: list[str]
    web_snapshot_ids: list[str]
    web_domains_used: list[str]
    ranking_scores: dict
    latency_ms: float
    token_usage: dict
    chat_context_enabled: bool
    rewrite_used: bool
    rewritten_query: str | None = None
    history_messages_used: int
    history_token_estimate: int
    history_trimmed: bool
    status: str
    created_at: datetime


class PendingRegistrationOut(BaseModel):
    id: str
    username: str
    email: str | None = None
    tenant_id: str
    enabled: bool
    created_at: datetime | None = None


DocumentStatus = Literal["draft", "processing", "approved", "archived", "failed"]
DocumentSourceType = Literal["upload", "website_snapshot"]


class DocumentChunkOut(BaseModel):
    id: str
    tenant_id: str
    document_id: str
    chunk_index: int
    content: str
    token_count: int
    embedding_model: str | None = None
    metadata_json: dict[str, Any]
    created_at: datetime


class DocumentOut(BaseModel):
    id: str
    tenant_id: str
    title: str
    source_type: DocumentSourceType
    mime_type: str | None = None
    file_name: str | None = None
    storage_path: str | None = None
    status: DocumentStatus
    enabled_in_retrieval: bool
    checksum: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None
    metadata_json: dict[str, Any]
    chunk_count: int = 0
    ingestion_error: str | None = None
    ingestion_error_at: datetime | None = None


class DocumentDetailOut(DocumentOut):
    chunks: list[DocumentChunkOut] = Field(default_factory=list)


class DocumentUploadForm(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    enabled_in_retrieval: bool = True
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_form(cls, title: str | None, enabled_in_retrieval: bool, metadata_json: str | None):
        parsed: dict[str, Any] = {}
        if metadata_json:
            try:
                raw = json.loads(metadata_json)
            except json.JSONDecodeError as exc:
                raise ValueError("metadata_json must be valid JSON") from exc
            if not isinstance(raw, dict):
                raise ValueError("metadata_json must be a JSON object")
            parsed = validate_document_metadata_json(raw)
        return cls(title=title, enabled_in_retrieval=enabled_in_retrieval, metadata_json=parsed)


class DocumentUpdateIn(BaseModel):
    enabled_in_retrieval: bool | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_json(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return value
        return validate_document_metadata_json(value)


class WebsiteSnapshotCreate(BaseModel):
    url: AnyHttpUrl
    title: str | None = Field(default=None, min_length=1, max_length=255)
    enabled_in_retrieval: bool = True
    tags: list[str] = Field(default_factory=list)

    @field_validator("url", mode="before")
    @classmethod
    def normalize_snapshot_url(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if re.fullmatch(r"https://[^/\s]+", stripped):
                return f"{stripped}/"
        return value

    @field_validator("url")
    @classmethod
    def validate_snapshot_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        parsed = urlparse(str(value))
        host = parsed.hostname or ""
        if parsed.scheme.lower() != "https":
            raise ValueError("url must use https")
        _resolve_public_host(host)
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)
