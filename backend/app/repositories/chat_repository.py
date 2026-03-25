from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.models import Chat, ErrorLog, Message, ResponseTrace


class ChatRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_chat(self, tenant_id: str, user_id: str, title: str) -> Chat:
        chat = Chat(tenant_id=tenant_id, user_id=user_id, title=title)
        self.db.add(chat)
        self.db.commit()
        self.db.refresh(chat)
        return chat

    def list_chats(self, tenant_id: str, user_id: str) -> list[Chat]:
        stmt = (
            select(Chat)
            .where(Chat.tenant_id == tenant_id, Chat.user_id == user_id)
            .order_by(Chat.updated_at.desc())
        )
        return list(self.db.scalars(stmt))

    def get_chat(self, tenant_id: str, user_id: str, chat_id: str) -> Chat | None:
        stmt = select(Chat).where(Chat.id == chat_id, Chat.tenant_id == tenant_id, Chat.user_id == user_id)
        return self.db.scalar(stmt)

    def update_chat_title(self, tenant_id: str, user_id: str, chat_id: str, title: str) -> Chat | None:
        chat = self.get_chat(tenant_id, user_id, chat_id)
        if not chat:
            return None
        chat.title = title
        self.db.commit()
        self.db.refresh(chat)
        return chat

    def delete_chat(self, tenant_id: str, user_id: str, chat_id: str) -> bool:
        chat = self.get_chat(tenant_id, user_id, chat_id)
        if not chat:
            return False
        self.db.execute(
            delete(Message).where(Message.tenant_id == tenant_id, Message.chat_id == chat.id)
        )
        self.db.execute(
            delete(ResponseTrace).where(ResponseTrace.tenant_id == tenant_id, ResponseTrace.chat_id == chat.id)
        )
        self.db.execute(
            delete(ErrorLog).where(ErrorLog.tenant_id == tenant_id, ErrorLog.chat_id == chat.id)
        )
        self.db.delete(chat)
        self.db.commit()
        return True

    def list_messages(self, tenant_id: str, chat_id: str) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.chat_id == chat_id)
            .order_by(Message.created_at.asc())
        )
        return list(self.db.scalars(stmt))

    def list_recent_messages(self, tenant_id: str, chat_id: str, limit: int) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.chat_id == chat_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(list(self.db.scalars(stmt))))

    def add_message(
        self,
        tenant_id: str,
        chat_id: str,
        user_id: str,
        role: str,
        content: str,
        source_types: list[str] | None = None,
    ) -> Message:
        message = Message(
            tenant_id=tenant_id,
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            content=content,
            source_types=source_types or [],
        )
        self.db.add(message)
        chat = self.db.get(Chat, chat_id)
        if chat:
            chat.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(message)
        return message

    def count_user_messages(self, tenant_id: str, user_id: str) -> int:
        stmt = select(func.count(Message.id)).where(
            Message.tenant_id == tenant_id,
            Message.user_id == user_id,
            Message.role == "user",
        )
        return int(self.db.scalar(stmt) or 0)

    def find_recent_user_message(
        self,
        tenant_id: str,
        chat_id: str,
        user_id: str,
        content: str,
        within_seconds: int = 180,
    ) -> Message | None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, within_seconds))
        stmt = (
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.chat_id == chat_id,
                Message.user_id == user_id,
                Message.role == "user",
                Message.content == content,
                Message.created_at >= cutoff,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)
