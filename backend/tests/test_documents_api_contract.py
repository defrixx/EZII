from datetime import UTC, datetime
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.core.security import AuthContext, require_admin
from app.main import app


class FakeAdminRepository:
    documents: dict[str, SimpleNamespace] = {}
    chunks: dict[str, list[SimpleNamespace]] = {}

    def __init__(self, db):
        self.db = db

    @classmethod
    def reset(cls):
        cls.documents = {}
        cls.chunks = {}

    def list_documents(self, tenant_id: str, source_type: str | None = None, status: str | None = None):
        rows = [doc for doc in self.documents.values() if doc.tenant_id == tenant_id]
        if source_type:
            rows = [doc for doc in rows if doc.source_type == source_type]
        if status:
            rows = [doc for doc in rows if doc.status == status]
        rows.sort(key=lambda doc: doc.created_at, reverse=True)
        return [(row, len(self.chunks.get(str(row.id), []))) for row in rows]

    def get_document(self, tenant_id: str, document_id: str):
        row = self.documents.get(document_id)
        if row and row.tenant_id == tenant_id:
            return row
        return None

    def get_document_with_chunk_count(self, tenant_id: str, document_id: str):
        row = self.get_document(tenant_id, document_id)
        if row is None:
            return None
        return row, len(self.chunks.get(document_id, []))

    def list_document_chunks(self, tenant_id: str, document_id: str):
        row = self.get_document(tenant_id, document_id)
        if row is None:
            return []
        return list(self.chunks.get(document_id, []))

    def update_document(self, row, payload: dict, auto_commit: bool = True):
        for key, value in payload.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(UTC)
        self.documents[str(row.id)] = row
        return row

    def add_audit_log(self, *args, **kwargs):
        return None


class FakeDocumentService:
    def __init__(self, db):
        self.db = db

    @classmethod
    def run_ingestion_job(cls, job_id: str):
        return None

    async def create_upload(self, tenant_id: str, user_id: str, file, payload):
        document_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        row = SimpleNamespace(
            id=document_id,
            tenant_id=tenant_id,
            title=payload.title or "Uploaded file",
            source_type="upload",
            mime_type=file.content_type or "text/plain",
            file_name=file.filename,
            storage_path=f"data/documents/{tenant_id}/{document_id}/{file.filename}",
            status="processing",
            enabled_in_retrieval=payload.enabled_in_retrieval,
            checksum="checksum",
            created_by=user_id,
            approved_by=None,
            created_at=now,
            updated_at=now,
            approved_at=None,
            metadata_json=payload.metadata_json,
        )
        FakeAdminRepository.documents[document_id] = row
        FakeAdminRepository.chunks[document_id] = [
            SimpleNamespace(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=0,
                content="hello world",
                token_count=2,
                embedding_model="text-embedding-3-small",
                metadata_json={"document_title": row.title},
                created_at=now,
            )
        ]
        return row, str(uuid.uuid4())

    def queue_reindex(self, row, triggered_by: str):
        row.status = "processing"
        row.updated_at = datetime.now(UTC)
        return str(uuid.uuid4())

    def approve_document(self, row, approved_by: str):
        row.status = "approved"
        row.approved_by = approved_by
        row.updated_at = datetime.now(UTC)
        row.approved_at = row.updated_at
        return row

    def archive_document(self, row):
        row.status = "archived"
        row.enabled_in_retrieval = False
        row.updated_at = datetime.now(UTC)
        return row

    def delete_document(self, row):
        FakeAdminRepository.documents.pop(str(row.id), None)
        FakeAdminRepository.chunks.pop(str(row.id), None)


def _ctx_override():
    return AuthContext(user_id="admin-1", tenant_id="tenant-1", email="admin@example.com", role="admin")


def _db_override():
    class FakeDb:
        def commit(self):
            return None

        def rollback(self):
            return None

        def refresh(self, row):
            return row

    return FakeDb()


def test_documents_lifecycle_endpoints(monkeypatch):
    from app.api.v1 import admin as admin_module

    FakeAdminRepository.reset()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module, "DocumentService", FakeDocumentService)
    monkeypatch.setattr(admin_module, "_schedule_document_ingestion", lambda background_tasks, job_id: None)

    app.dependency_overrides[require_admin] = _ctx_override
    app.dependency_overrides[db_dep] = _db_override
    client = TestClient(app)

    try:
        r_upload = client.post(
            "/api/v1/admin/documents/upload",
            data={"title": "Policy", "enabled_in_retrieval": "true", "metadata_json": '{"category":"policy"}'},
            files={"file": ("policy.txt", b"hello world", "text/plain")},
        )
        assert r_upload.status_code == 200
        uploaded = r_upload.json()
        document_id = uploaded["id"]
        assert uploaded["status"] == "processing"
        assert uploaded["chunk_count"] == 1

        r_list = client.get("/api/v1/admin/documents")
        assert r_list.status_code == 200
        assert len(r_list.json()) == 1

        r_get = client.get(f"/api/v1/admin/documents/{document_id}")
        assert r_get.status_code == 200
        assert len(r_get.json()["chunks"]) == 1

        r_approve = client.post(f"/api/v1/admin/documents/{document_id}/approve")
        assert r_approve.status_code == 200
        assert r_approve.json()["status"] == "approved"

        r_reindex = client.post(f"/api/v1/admin/documents/{document_id}/reindex")
        assert r_reindex.status_code == 200
        assert r_reindex.json()["status"] == "processing"

        r_archive = client.post(f"/api/v1/admin/documents/{document_id}/archive")
        assert r_archive.status_code == 200
        assert r_archive.json()["status"] == "archived"
        assert r_archive.json()["enabled_in_retrieval"] is False

        r_delete = client.delete(f"/api/v1/admin/documents/{document_id}")
        assert r_delete.status_code == 200

        r_missing = client.get(f"/api/v1/admin/documents/{document_id}")
        assert r_missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
