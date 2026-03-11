from datetime import datetime
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_LIST_ITEMS = 50
MAX_LIST_ITEM_LENGTH = 255
MAX_METADATA_JSON_BYTES = 8192


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
    @field_validator("synonyms", "forbidden_interpretations")
    @classmethod
    def validate_string_list(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError(f"Список не должен содержать больше {MAX_LIST_ITEMS} элементов")
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > MAX_LIST_ITEM_LENGTH:
                raise ValueError(f"Элемент списка не должен быть длиннее {MAX_LIST_ITEM_LENGTH} символов")
            cleaned.append(text)
        return cleaned

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_json(cls, value: dict) -> dict:
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_METADATA_JSON_BYTES:
            raise ValueError(f"metadata_json превышает лимит {MAX_METADATA_JSON_BYTES} байт")
        return value


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

    @field_validator("synonyms", "forbidden_interpretations")
    @classmethod
    def validate_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError(f"Список не должен содержать больше {MAX_LIST_ITEMS} элементов")
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > MAX_LIST_ITEM_LENGTH:
                raise ValueError(f"Элемент списка не должен быть длиннее {MAX_LIST_ITEM_LENGTH} символов")
            cleaned.append(text)
        return cleaned

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_json(cls, value: dict | None) -> dict | None:
        if value is None:
            return value
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_METADATA_JSON_BYTES:
            raise ValueError(f"metadata_json превышает лимит {MAX_METADATA_JSON_BYTES} байт")
        return value


class GlossaryEntryOut(GlossaryEntryBase):
    id: str
    tenant_id: str
    glossary_id: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None


class GlossaryImportRow(GlossaryEntryBase):
    @field_validator("synonyms", "forbidden_interpretations")
    @classmethod
    def validate_string_list(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_LIST_ITEMS:
            raise ValueError(f"Список не должен содержать больше {MAX_LIST_ITEMS} элементов")
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > MAX_LIST_ITEM_LENGTH:
                raise ValueError(f"Элемент списка не должен быть длиннее {MAX_LIST_ITEM_LENGTH} символов")
            cleaned.append(text)
        return cleaned

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_json(cls, value: dict) -> dict:
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_METADATA_JSON_BYTES:
            raise ValueError(f"metadata_json превышает лимит {MAX_METADATA_JSON_BYTES} байт")
        return value


class GlossaryImportRequest(BaseModel):
    rows: list[GlossaryImportRow]


class GlossaryExportResponse(BaseModel):
    rows: list[GlossaryEntryOut]
