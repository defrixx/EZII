from datetime import datetime
from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChatUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChatOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    strict_glossary_mode: bool | None = None
    is_retry: bool = False


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    source_types: list[str] = Field(default_factory=list)
    created_at: datetime


class ChatDetail(BaseModel):
    chat: ChatOut
    messages: list[MessageOut]
