import json
import ipaddress
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
KnowledgeMode = Literal["glossary_only", "glossary_documents", "glossary_documents_web", "glossary_github_documents_web"]
EmptyRetrievalMode = Literal["strict_fallback", "model_only_fallback", "clarifying_fallback"]
AnswerMode = Literal["grounded", "strict_fallback", "model_only", "clarifying", "error"]
MAX_DOCUMENT_METADATA_JSON_BYTES = 8192
MAX_TAGS = 50
MAX_TAG_LENGTH = 64


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
    if len(raw) > MAX_TAGS:
        raise ValueError(f"tags must not contain more than {MAX_TAGS} items")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = str(item or "").strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"tag length must not exceed {MAX_TAG_LENGTH} characters")
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
        if not _is_public_host(host):
            raise ValueError("base_url host must be public")
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


class QdrantResetAllIn(BaseModel):
    embedding_vector_size: int = Field(ge=64, le=8192)
    confirm_phrase: str = Field(min_length=8, max_length=128)
    confirm_phrase_repeat: str = Field(min_length=8, max_length=128)


class QdrantResetAllOut(BaseModel):
    deleted_collections: list[str]
    recreated_collections: list[str]
    embedding_vector_size: int


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


class SourceImpactMetricOut(BaseModel):
    source_id: str
    usage_count: int
    last_used_at: datetime | None = None


class SourceImpactItemOut(BaseModel):
    id: str
    title: str
    source_type: Literal["upload", "website_snapshot", "github_playbook"]
    status: Literal["draft", "processing", "approved", "archived", "failed"]
    enabled_in_retrieval: bool
    usage_count: int
    last_used_at: datetime | None = None
    updated_at: datetime


class SourceImpactOut(BaseModel):
    window_days: int
    total_sources: int
    used_sources: int
    unused_sources: int
    top_used: list[SourceImpactItemOut] = Field(default_factory=list)
    never_used: list[SourceImpactItemOut] = Field(default_factory=list)
    metrics: list[SourceImpactMetricOut] = Field(default_factory=list)


class UserTokenUsageOut(BaseModel):
    user_id: str
    email: str
    role: Literal["admin", "user"]
    request_count: int
    provider_prompt_tokens: int
    provider_completion_tokens: int
    provider_total_tokens: int
    rewrite_total_tokens: int
    total_tokens: int
    avg_tokens_per_request: float
    last_request_at: datetime | None = None


class UserTokenUsageSummaryOut(BaseModel):
    month_start: datetime
    month_end: datetime
    month_total_tokens: int
    month_prompt_tokens: int
    month_completion_tokens: int
    month_rewrite_tokens: int
    month_request_count: int
    active_users_in_month: int
    total_users: int
    avg_tokens_per_request: float
    avg_tokens_per_active_user: float
    avg_daily_tokens: float
    projected_month_total_tokens: float


class UserTokenUsagePageOut(BaseModel):
    window_days: int
    sort_order: Literal["asc", "desc"]
    page: int
    page_size: int
    total: int
    items: list[UserTokenUsageOut] = Field(default_factory=list)
    summary: UserTokenUsageSummaryOut


class PendingRegistrationOut(BaseModel):
    id: str
    username: str
    email: str | None = None
    tenant_id: str
    enabled: bool
    created_at: datetime | None = None


DocumentStatus = Literal["draft", "processing", "approved", "archived", "failed"]
DocumentSourceType = Literal["upload", "website_snapshot", "github_playbook"]


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


class DocumentListOut(BaseModel):
    items: list[DocumentOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class PlaybookSyncOut(BaseModel):
    repository: str
    branch: str
    commit_sha: str
    total_files: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    archived: int = 0
    failed: int = 0
    queued_document_ids: list[str] = Field(default_factory=list)
    queued_job_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PlaybookDeleteOut(BaseModel):
    repository: str
    deleted: int = 0


class PlaybookApproveOut(BaseModel):
    repository: str
    approved: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)


class DocumentDetailOut(DocumentOut):
    chunks: list[DocumentChunkOut] = Field(default_factory=list)


class DocumentUploadForm(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    enabled_in_retrieval: bool = True
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        text = str(value).strip()
        return text or None

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

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        text = str(value).strip()
        return text or None

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
        if not _is_public_host(host):
            raise ValueError("url host must be public")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        return normalize_tags(value)
