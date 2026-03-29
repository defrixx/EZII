from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class ChatCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return str(value).strip()


class ChatUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    is_pinned: bool | None = None
    is_archived: bool | None = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class ChatOut(BaseModel):
    id: str
    title: str
    is_pinned: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    strict_glossary_mode: bool | None = None
    is_retry: bool = False

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return str(value).strip()


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    source_types: list[str] = Field(default_factory=list)
    created_at: datetime


class ChatDetail(BaseModel):
    chat: ChatOut
    messages: list[MessageOut]
