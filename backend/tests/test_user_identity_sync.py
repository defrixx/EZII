from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.deps import ensure_user_exists
from app.core.security import AuthContext


class FakeDb:
    def __init__(self, scalar_values: list[object], commit_exc: Exception | None = None):
        self.scalar_values = list(scalar_values)
        self.commit_exc = commit_exc
        self.commits = 0
        self.rollbacks = 0
        self.added = []

    def scalar(self, stmt):
        if not self.scalar_values:
            return None
        return self.scalar_values.pop(0)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1
        if self.commit_exc is not None:
            raise self.commit_exc

    def rollback(self):
        self.rollbacks += 1


def _ctx(user_id: str = "00000000-0000-0000-0000-000000000111") -> AuthContext:
    return AuthContext(
        user_id=user_id,
        tenant_id="00000000-0000-0000-0000-000000000001",
        email="user@example.com",
        role="user",
    )


def test_ensure_user_exists_rejects_different_subject_for_same_email():
    db = FakeDb(
        scalar_values=[
            None,
            SimpleNamespace(id="00000000-0000-0000-0000-000000000999", role="user"),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        ensure_user_exists(db, _ctx())

    assert exc.value.status_code == 409
    assert "identity conflict" in str(exc.value.detail).lower()


def test_ensure_user_exists_rejects_identity_conflict_after_integrity_error():
    db = FakeDb(
        scalar_values=[
            None,
            None,
            SimpleNamespace(id="00000000-0000-0000-0000-000000000999", role="user"),
        ],
        commit_exc=IntegrityError("insert", {}, Exception("duplicate key")),
    )

    with pytest.raises(HTTPException) as exc:
        ensure_user_exists(db, _ctx())

    assert exc.value.status_code == 409
    assert db.rollbacks == 1

