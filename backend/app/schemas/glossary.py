from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GlossaryBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    priority: int = Field(default=100, ge=1, le=1000)
    enabled: bool = True


class GlossaryCreate(GlossaryBase):
    pass


class GlossaryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    enabled: bool | None = None


class GlossaryOut(GlossaryBase):
    id: str
    tenant_id: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class GlossaryEntryBase(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    definition: str = Field(min_length=1, max_length=4000)
    example: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    forbidden_interpretations: list[str] = Field(default_factory=list)
    owner: str | None = None
    version: int = Field(default=1, ge=1, le=10_000)
    priority: int = Field(default=100, ge=1, le=1000)
    status: Literal["active", "draft", "disabled", "archived"] = "active"
    metadata_json: dict = Field(default_factory=dict)


class GlossaryEntryCreate(GlossaryEntryBase):
    pass


class GlossaryEntryUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=255)
    definition: str | None = Field(default=None, min_length=1, max_length=4000)
    example: str | None = None
    synonyms: list[str] | None = None
    forbidden_interpretations: list[str] | None = None
    owner: str | None = None
    version: int | None = Field(default=None, ge=1, le=10_000)
    priority: int | None = Field(default=None, ge=1, le=1000)
    status: Literal["active", "draft", "disabled", "archived"] | None = None
    metadata_json: dict | None = None


class GlossaryEntryOut(GlossaryEntryBase):
    id: str
    tenant_id: str
    glossary_id: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None


class GlossaryImportRow(GlossaryEntryBase):
    pass


class GlossaryImportRequest(BaseModel):
    rows: list[GlossaryImportRow]


class GlossaryExportResponse(BaseModel):
    rows: list[GlossaryEntryOut]
