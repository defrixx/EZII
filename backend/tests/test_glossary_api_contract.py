from datetime import datetime, UTC
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

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

    def find_entry_by_term(self, tenant_id: str, glossary_id: str, term: str):
        normalized = term.strip().lower()
        for row in self.entries.values():
            if row.tenant_id == tenant_id and row.glossary_id == glossary_id and row.term.strip().lower() == normalized:
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


def test_clear_default_glossary_entries(monkeypatch):
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

        first = client.post(
            f"/api/v1/glossary/{default_id}/entries",
            json={"term": "SLA", "definition": "Service level agreement", "synonyms": [], "forbidden_interpretations": []},
        )
        second = client.post(
            f"/api/v1/glossary/{default_id}/entries",
            json={"term": "RTO", "definition": "Recovery time objective", "synonyms": [], "forbidden_interpretations": []},
        )
        assert first.status_code == 200
        assert second.status_code == 200

        before = client.get(f"/api/v1/glossary/{default_id}/entries")
        assert before.status_code == 200
        assert len(before.json()) == 2

        cleared = client.post("/api/v1/glossary/default/clear")
        assert cleared.status_code == 200
        assert cleared.json()["glossary_id"] == default_id
        assert cleared.json()["deleted"] == 2

        after = client.get(f"/api/v1/glossary/{default_id}/entries")
        assert after.status_code == 200
        assert after.json() == []
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


def test_glossary_csv_import_upserts_by_term(monkeypatch):
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

        r_seed = client.post(
            f"/api/v1/glossary/{glossary_id}/entries",
            json={"term": "SLA", "definition": "Old definition", "synonyms": [], "forbidden_interpretations": []},
        )
        assert r_seed.status_code == 200

        csv_bytes = (
            "term,definition,synonyms,tags\n"
            "SLA,Updated definition,service level,policies;ops\n"
            "RTO,Recovery time objective,recovery target,continuity\n"
        ).encode("utf-8")
        r_import = client.post(
            f"/api/v1/glossary/{glossary_id}/import-csv",
            files={"file": ("glossary.csv", csv_bytes, "text/csv")},
        )
        assert r_import.status_code == 200
        assert r_import.json() == {"created": 1, "updated": 1}

        r_list_entries = client.get(f"/api/v1/glossary/{glossary_id}/entries")
        assert r_list_entries.status_code == 200
        payload = r_list_entries.json()
        assert len(payload) == 2
        sla = next(entry for entry in payload if entry["term"] == "SLA")
        rto = next(entry for entry in payload if entry["term"] == "RTO")
        assert sla["definition"] == "Updated definition"
        assert sla["metadata_json"]["tags"] == ["policies", "ops"]
        assert rto["synonyms"] == ["recovery target"]
    finally:
        app.dependency_overrides.clear()


def test_delete_glossary_returns_409_on_fk_conflict(monkeypatch):
    from app.api.v1 import glossary as glossary_module

    class FKConflictGlossaryRepository(FakeGlossaryRepository):
        def delete_glossary(self, row):
            raise IntegrityError("DELETE FROM glossaries", {"id": str(row.id)}, Exception("fk violation"))

    FakeGlossaryRepository.reset()
    monkeypatch.setattr(glossary_module, "GlossaryRepository", FKConflictGlossaryRepository)
    monkeypatch.setattr(glossary_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(glossary_module, "RetrievalService", FakeRetrievalService)

    app.dependency_overrides[require_admin] = _ctx_override
    app.dependency_overrides[db_dep] = _db_override
    client = TestClient(app)
    try:
        r_create_glossary = client.post(
            "/api/v1/glossary",
            json={"name": "Delete test", "description": "x", "priority": 10, "enabled": True},
        )
        assert r_create_glossary.status_code == 200
        glossary_id = r_create_glossary.json()["id"]

        r_delete = client.delete(f"/api/v1/glossary/{glossary_id}")
        assert r_delete.status_code == 409
        assert "related entries still exist" in r_delete.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_glossary_csv_import_fails_closed_when_embeddings_unavailable(monkeypatch):
    from app.api.v1 import glossary as glossary_module

    class FailingProvider:
        async def embeddings(self, inputs):
            raise RuntimeError("embeddings offline")

    class FailingRetrievalService(FakeRetrievalService):
        def _provider_for_tenant(self, tenant_id: str):
            return FailingProvider()

    FakeGlossaryRepository.reset()
    monkeypatch.setattr(glossary_module, "GlossaryRepository", FakeGlossaryRepository)
    monkeypatch.setattr(glossary_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(glossary_module, "RetrievalService", FailingRetrievalService)

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

        r_seed = client.post(
            f"/api/v1/glossary/{glossary_id}/entries",
            json={"term": "SLA", "definition": "Old definition", "synonyms": [], "forbidden_interpretations": []},
        )
        assert r_seed.status_code == 502

        csv_bytes = (
            "term,definition,synonyms,tags\n"
            "SLA,Updated definition,service level,policies;ops\n"
            "RTO,Recovery time objective,recovery target,continuity\n"
        ).encode("utf-8")
        r_import = client.post(
            f"/api/v1/glossary/{glossary_id}/import-csv",
            files={"file": ("glossary.csv", csv_bytes, "text/csv")},
        )
        assert r_import.status_code == 502
        assert "Failed to generate embeddings for glossary import" in r_import.json()["detail"]

        r_list_entries = client.get(f"/api/v1/glossary/{glossary_id}/entries")
        assert r_list_entries.status_code == 200
        entries = r_list_entries.json()
        assert len(entries) == 1
        assert entries[0]["term"] == "SLA"
        assert entries[0]["definition"] == "Old definition"
    finally:
        app.dependency_overrides.clear()
