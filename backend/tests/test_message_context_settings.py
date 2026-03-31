from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.security import AuthContext
from app.schemas.chat import MessageCreate


def _ctx() -> AuthContext:
    return AuthContext(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        email="user@example.com",
        role="user",
    )


class _FakeDb:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_prepare_message_request_skips_chat_context_when_disabled(monkeypatch):
    from app.api.v1 import messages as messages_module

    stored_messages: list[tuple[str, str]] = []

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

        def get_chat(self, tenant_id: str, user_id: str, chat_id: str):
            return SimpleNamespace(id=chat_id)

        def count_user_messages(self, tenant_id: str, user_id: str) -> int:
            return 0

        def add_message(self, tenant_id: str, chat_id: str, user_id: str, role: str, content: str):
            stored_messages.append((role, content))
            return SimpleNamespace(id="msg-current", role=role, content=content, created_at=datetime.now(UTC))

        def list_recent_messages(self, tenant_id: str, chat_id: str, limit: int):
            raise AssertionError("History should not be loaded when chat context is disabled")

        def has_assistant_reply_after(self, tenant_id: str, chat_id: str, *, after_created_at):
            return False

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return SimpleNamespace(
                knowledge_mode="glossary_documents",
                empty_retrieval_mode="model_only_fallback",
                strict_glossary_mode=False,
                show_confidence=False,
                response_tone="consultative_supportive",
                max_user_messages_total=5,
                chat_context_enabled=False,
                history_user_turn_limit=6,
                history_message_limit=12,
                history_token_budget=1200,
                rewrite_history_message_limit=8,
            )

    monkeypatch.setattr(messages_module, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(messages_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(messages_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(messages_module, "AdminRepository", FakeAdminRepository)

    prep = messages_module._prepare_message_request_sync(
        _ctx(),
        "chat-1",
        MessageCreate(content="New question"),
    )

    assert stored_messages == [("user", "New question")]
    assert prep.chat_context_enabled is False
    assert prep.conversation_history == []
    assert prep.rewrite_history == []
    assert prep.history_messages_used == 0
    assert prep.history_token_estimate == 0
    assert prep.history_trimmed is False


def test_prepare_message_request_applies_provider_history_limits(monkeypatch):
    from app.api.v1 import messages as messages_module

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

        def get_chat(self, tenant_id: str, user_id: str, chat_id: str):
            return SimpleNamespace(id=chat_id)

        def count_user_messages(self, tenant_id: str, user_id: str) -> int:
            return 0

        def add_message(self, tenant_id: str, chat_id: str, user_id: str, role: str, content: str):
            return SimpleNamespace(id="msg-current", role=role, content=content, created_at=datetime.now(UTC))

        def list_recent_messages(self, tenant_id: str, chat_id: str, limit: int):
            assert limit == 5
            return [
                SimpleNamespace(id="u1", role="user", content="First question"),
                SimpleNamespace(id="a1", role="assistant", content="First answer"),
                SimpleNamespace(id="u2", role="user", content="Second question"),
                SimpleNamespace(id="a2", role="assistant", content="Second answer"),
                SimpleNamespace(id="msg-current", role="user", content="Current question"),
            ]

        def has_assistant_reply_after(self, tenant_id: str, chat_id: str, *, after_created_at):
            return False

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return SimpleNamespace(
                knowledge_mode="glossary_documents",
                empty_retrieval_mode="model_only_fallback",
                strict_glossary_mode=False,
                show_confidence=False,
                response_tone="consultative_supportive",
                max_user_messages_total=10,
                chat_context_enabled=True,
                history_user_turn_limit=2,
                history_message_limit=4,
                history_token_budget=1000,
                rewrite_history_message_limit=1,
            )

    monkeypatch.setattr(messages_module, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(messages_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(messages_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(messages_module, "AdminRepository", FakeAdminRepository)

    prep = messages_module._prepare_message_request_sync(
        _ctx(),
        "chat-1",
        MessageCreate(content="Current question"),
    )

    assert prep.chat_context_enabled is True
    assert [item["content"] for item in prep.conversation_history] == [
        "First question",
        "First answer",
        "Second question",
        "Second answer",
    ]
    assert prep.history_messages_used == 4
    assert prep.rewrite_history == [{"role": "assistant", "content": "Second answer"}]
    assert prep.history_token_estimate > 0
    assert prep.history_trimmed is False


def test_prepare_message_request_allows_retry_without_consuming_limit(monkeypatch):
    from app.api.v1 import messages as messages_module

    stored_messages: list[tuple[str, str]] = []

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

        def get_chat(self, tenant_id: str, user_id: str, chat_id: str):
            return SimpleNamespace(id=chat_id)

        def count_user_messages(self, tenant_id: str, user_id: str) -> int:
            return 5

        def find_recent_user_message(
            self,
            tenant_id: str,
            chat_id: str,
            user_id: str,
            content: str,
            within_seconds: int = 180,
        ):
            return SimpleNamespace(
                id="msg-existing",
                role="user",
                content=content,
                created_at=datetime.now(UTC),
            )

        def has_assistant_reply_after(self, tenant_id: str, chat_id: str, *, after_created_at):
            return False

        def add_message(self, tenant_id: str, chat_id: str, user_id: str, role: str, content: str):
            stored_messages.append((role, content))
            return SimpleNamespace(id="msg-new", role=role, content=content, created_at=datetime.now(UTC))

        def list_recent_messages(self, tenant_id: str, chat_id: str, limit: int):
            return []

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return SimpleNamespace(
                knowledge_mode="glossary_documents",
                empty_retrieval_mode="model_only_fallback",
                strict_glossary_mode=False,
                show_confidence=False,
                response_tone="consultative_supportive",
                max_user_messages_total=5,
                chat_context_enabled=False,
                history_user_turn_limit=6,
                history_message_limit=12,
                history_token_budget=1200,
                rewrite_history_message_limit=8,
            )

    monkeypatch.setattr(messages_module, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(messages_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(messages_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(messages_module, "AdminRepository", FakeAdminRepository)

    prep = messages_module._prepare_message_request_sync(
        _ctx(),
        "chat-1",
        MessageCreate(content="Repeat this answer", is_retry=True),
    )

    assert prep.chat_context_enabled is False
    assert stored_messages == []


def test_prepare_message_request_rejects_new_message_when_limit_exceeded(monkeypatch):
    from app.api.v1 import messages as messages_module

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

        def get_chat(self, tenant_id: str, user_id: str, chat_id: str):
            return SimpleNamespace(id=chat_id)

        def count_user_messages(self, tenant_id: str, user_id: str) -> int:
            return 5

        def count_user_messages_since(self, tenant_id: str, user_id: str, since):
            return 5

        def find_recent_user_message(
            self,
            tenant_id: str,
            chat_id: str,
            user_id: str,
            content: str,
            within_seconds: int = 180,
        ):
            return None

        def has_assistant_reply_after(self, tenant_id: str, chat_id: str, *, after_created_at):
            return False

        def add_message(self, tenant_id: str, chat_id: str, user_id: str, role: str, content: str):
            raise AssertionError("add_message must not be called when limit is exceeded")

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return SimpleNamespace(
                knowledge_mode="glossary_documents",
                empty_retrieval_mode="model_only_fallback",
                strict_glossary_mode=False,
                show_confidence=False,
                response_tone="consultative_supportive",
                max_user_messages_total=5,
                chat_context_enabled=False,
                history_user_turn_limit=6,
                history_message_limit=12,
                history_token_budget=1200,
                rewrite_history_message_limit=8,
            )

    monkeypatch.setattr(messages_module, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(messages_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(messages_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(messages_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(messages_module, "limit_window_start_utc", lambda *_args, **_kwargs: datetime(2026, 3, 31, 0, 0, tzinfo=UTC))
    monkeypatch.setattr(messages_module, "limit_window_reset_at_utc", lambda *_args, **_kwargs: datetime(2026, 4, 1, 0, 0, tzinfo=UTC))

    with pytest.raises(HTTPException) as exc_info:
        messages_module._prepare_message_request_sync(
            _ctx(),
            "chat-1",
            MessageCreate(content="Repeat this answer", is_retry=True),
        )
    assert exc_info.value.status_code == 403
    assert str(exc_info.value.detail) == "Message limit reached (5). Limit will reset on 2026-04-01 00:00 UTC."


def test_prepare_message_request_counts_retry_as_new_turn_when_prior_answer_exists(monkeypatch):
    from app.api.v1 import messages as messages_module

    stored_messages: list[tuple[str, str]] = []

    class FakeChatRepository:
        def __init__(self, db):
            self.db = db

        def get_chat(self, tenant_id: str, user_id: str, chat_id: str):
            return SimpleNamespace(id=chat_id)

        def count_user_messages(self, tenant_id: str, user_id: str) -> int:
            return 4

        def find_recent_user_message(
            self,
            tenant_id: str,
            chat_id: str,
            user_id: str,
            content: str,
            within_seconds: int = 180,
        ):
            return SimpleNamespace(
                id="msg-existing",
                role="user",
                content=content,
                created_at=datetime.now(UTC),
            )

        def has_assistant_reply_after(self, tenant_id: str, chat_id: str, *, after_created_at):
            return True

        def add_message(self, tenant_id: str, chat_id: str, user_id: str, role: str, content: str):
            stored_messages.append((role, content))
            return SimpleNamespace(id="msg-new", role=role, content=content, created_at=datetime.now(UTC))

        def list_recent_messages(self, tenant_id: str, chat_id: str, limit: int):
            return []

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def get_provider(self, tenant_id: str):
            return SimpleNamespace(
                knowledge_mode="glossary_documents",
                empty_retrieval_mode="model_only_fallback",
                strict_glossary_mode=False,
                show_confidence=False,
                response_tone="consultative_supportive",
                max_user_messages_total=5,
                chat_context_enabled=False,
                history_user_turn_limit=6,
                history_message_limit=12,
                history_token_budget=1200,
                rewrite_history_message_limit=8,
            )

    monkeypatch.setattr(messages_module, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(messages_module, "ensure_user_exists", lambda db, ctx: None)
    monkeypatch.setattr(messages_module, "ChatRepository", FakeChatRepository)
    monkeypatch.setattr(messages_module, "AdminRepository", FakeAdminRepository)

    prep = messages_module._prepare_message_request_sync(
        _ctx(),
        "chat-1",
        MessageCreate(content="Repeat this answer", is_retry=True),
    )

    assert prep.chat_context_enabled is False
    assert stored_messages == [("user", "Repeat this answer")]
