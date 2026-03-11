from datetime import datetime
import ipaddress
import re
from typing import Literal
from urllib.parse import urlparse
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


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


class AllowlistDomainCreate(BaseModel):
    domain: str = Field(min_length=3, max_length=255)
    notes: str | None = None
    enabled: bool = True

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        domain = value.strip().lower()
        if not DOMAIN_RE.fullmatch(domain):
            raise ValueError("Неверный формат домена")
        if not _is_public_host(domain):
            raise ValueError("Домен должен резолвиться в публичные сетевые адреса")
        return domain


class AllowlistDomainUpdate(BaseModel):
    domain: str | None = Field(default=None, min_length=3, max_length=255)
    notes: str | None = None
    enabled: bool | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str | None) -> str | None:
        if value is None:
            return value
        domain = value.strip().lower()
        if not DOMAIN_RE.fullmatch(domain):
            raise ValueError("Неверный формат домена")
        if not _is_public_host(domain):
            raise ValueError("Домен должен резолвиться в публичные сетевые адреса")
        return domain


class AllowlistDomainOut(BaseModel):
    id: str
    domain: str
    notes: str | None = None
    enabled: bool
    created_at: datetime


class ProviderSettingsIn(BaseModel):
    base_url: AnyHttpUrl
    api_key: str | None = Field(default=None, min_length=16, max_length=1024)
    model_name: str = Field(min_length=2, max_length=255)
    embedding_model: str = Field(min_length=2, max_length=255)
    timeout_s: int = Field(default=30, ge=1, le=120)
    retry_policy: int = Field(default=2, ge=0, le=5)
    strict_glossary_mode: bool = False
    web_enabled: bool = False
    show_confidence: bool = False
    show_source_tags: bool = True
    response_tone: Literal["consultative_supportive", "neutral_reference"] = "consultative_supportive"
    max_user_messages_total: int = Field(default=5, ge=1, le=10000)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        parsed = urlparse(str(value))
        host = parsed.hostname or ""
        if parsed.scheme.lower() != "https":
            raise ValueError("base_url должен использовать https")
        if not _is_public_host(host):
            raise ValueError("Хост base_url должен резолвиться в публичные сетевые адреса")
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
    strict_glossary_mode: bool
    web_enabled: bool
    show_confidence: bool
    show_source_tags: bool
    response_tone: Literal["consultative_supportive", "neutral_reference"]
    max_user_messages_total: int
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
    glossary_entries_used: list[str]
    web_domains_used: list[str]
    ranking_scores: dict
    latency_ms: float
    token_usage: dict
    status: str
    created_at: datetime


class PendingRegistrationOut(BaseModel):
    id: str
    username: str
    email: str | None = None
    tenant_id: str
    enabled: bool
    created_at: datetime | None = None
