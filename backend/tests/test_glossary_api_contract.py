from datetime import datetime, UTC
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.core.security import AuthContext, require_admin
from app.main import app


class FakeGlossaryRepository:
    glossaries: dict[str, SimpleNamespace] = {}
    entries: dict[str, SimpleNamespace] = {}

    def __init__(self, db):
        self.db = db

    @classmethod
    def reset(cls):
        cls.glossaries = {}
        cls.entries = {}
        default_id = str(uuid.uuid4())
        cls.glossaries[default_id] = SimpleNamespace(
            id=default_id,
            tenant_id="tenant-1",
            name="Default",
            description="default glossary",
            priority=100,
            enabled=True,
            is_default=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def list_glossaries(self, tenant_id: str):
        return [g for g in self.glossaries.values() if g.tenant_id == tenant_id]

    def create_glossary(self, tenant_id: str, payload: dict):
        gid = str(uuid.uuid4())
        row = SimpleNamespace(
            id=gid,
            tenant_id=tenant_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            is_default=False,
            **payload,
        )
        self.glossaries[gid] = row
        return row

    def get_glossary(self, tenant_id: str, glossary_id: str):
        row = self.glossaries.get(glossary_id)
        if row and row.tenant_id == tenant_id:
            return row
        return None

    def update_glossary(self, row, payload: dict):
        for k, v in payload.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC)
        return row

    def delete_glossary(self, row):
        for eid, entry in list(self.entries.items()):
            if entry.glossary_id == row.id:
                del self.entries[eid]
        del self.glossaries[str(row.id)]

    def list_entries(self, tenant_id: str, glossary_id: str):
        return [e for e in self.entries.values() if e.tenant_id == tenant_id and e.glossary_id == glossary_id]

    def create_entry(self, tenant_id: str, glossary_id: str, created_by: str, payload: dict):
        eid = str(uuid.uuid4())
        row = SimpleNamespace(
            id=eid,
            tenant_id=tenant_id,
            glossary_id=glossary_id,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            **payload,
        )
        self.entries[eid] = row
        return row

    def get_entry(self, tenant_id: str, glossary_id: str, entry_id: str):
        row = self.entries.get(entry_id)
        if row and row.tenant_id == tenant_id and row.glossary_id == glossary_id:
            return row
        return None

    def update_entry(self, row, payload: dict):
        for k, v in payload.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC)
        return row

    def delete_entry(self, row):
        del self.entries[str(row.id)]


class FakeAdminRepository:
    def __init__(self, db):
        self.db = db

    def add_audit_log(self, *args, **kwargs):
        return None


class FakeProvider:
    async def embeddings(self, inputs):
        return [[0.01, 0.02, 0.03] for _ in inputs]


class FakeVector:
    def upsert_entry(self, *args, **kwargs):
        return None

    def delete_entry(self, *args, **kwargs):
        return None


class FakeRetrievalService:
    def __init__(self, db):
        self.db = db
        self.vector = FakeVector()

    def _provider_for_tenant(self, tenant_id: str):
        return FakeProvider()


def _ctx_override():
    return AuthContext(user_id="admin-1", tenant_id="tenant-1", email="admin@example.com", role="admin")


def _db_override():
    return object()


def setup_module():
    FakeGlossaryRepository.reset()


def test_glossary_default_protected(monkeypatch):
    from app.api.v1 import glossary as glossary_module

    FakeGlossaryRepository.reset()
    monkeypatch.setattr(glossary_module, "GlossaryRepository", FakeGlossaryRepository)
    monkeypatch.setattr(glossary_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(glossary_module, "RetrievalService", FakeRetrievalService)

    app.dependency_overrides[require_admin] = _ctx_override
    app.dependency_overrides[db_dep] = _db_override
    client = TestClient(app)

    try:
        default_id = next(iter(FakeGlossaryRepository.glossaries.keys()))

        r_disable = client.patch(f"/api/v1/glossary/{default_id}", json={"enabled": False})
        assert r_disable.status_code == 400

        r_delete = client.delete(f"/api/v1/glossary/{default_id}")
        assert r_delete.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_glossary_and_entries_crud(monkeypatch):
    from app.api.v1 import glossary as glossary_module

    FakeGlossaryRepository.reset()
    monkeypatch.setattr(glossary_module, "GlossaryRepository", FakeGlossaryRepository)
    monkeypatch.setattr(glossary_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(glossary_module, "RetrievalService", FakeRetrievalService)

    app.dependency_overrides[require_admin] = _ctx_override
    app.dependency_overrides[db_dep] = _db_override
    client = TestClient(app)
    try:
        r_create_glossary = client.post(
            "/api/v1/glossary",
            json={"name": "Policies", "description": "company policies", "priority": 10, "enabled": True},
        )
        assert r_create_glossary.status_code == 200
        glossary_id = r_create_glossary.json()["id"]

        r_create_entry = client.post(
            f"/api/v1/glossary/{glossary_id}/entries",
            json={
                "term": "SLA",
                "definition": "Service level agreement",
                "synonyms": ["service level"],
                "forbidden_interpretations": [],
            },
        )
        assert r_create_entry.status_code == 200
        entry_id = r_create_entry.json()["id"]

        r_list_entries = client.get(f"/api/v1/glossary/{glossary_id}/entries")
        assert r_list_entries.status_code == 200
        assert len(r_list_entries.json()) == 1

        r_update_entry = client.patch(
            f"/api/v1/glossary/{glossary_id}/entries/{entry_id}",
            json={"definition": "Updated definition", "priority": 5},
        )
        assert r_update_entry.status_code == 200
        assert r_update_entry.json()["definition"] == "Updated definition"

        r_delete_entry = client.delete(f"/api/v1/glossary/{glossary_id}/entries/{entry_id}")
        assert r_delete_entry.status_code == 200

        r_delete_glossary = client.delete(f"/api/v1/glossary/{glossary_id}")
        assert r_delete_glossary.status_code == 200
    finally:
        app.dependency_overrides.clear()
