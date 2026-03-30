from datetime import UTC, datetime
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
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

    def list_documents(
        self,
        tenant_id: str,
        source_type: str | None = None,
        status: str | None = None,
        *,
        search: str | None = None,
        tag: str | None = None,
        unused_only: bool = False,
        unused_window_days: int = 30,
        page: int = 1,
        page_size: int = 50,
    ):
        rows = [doc for doc in self.documents.values() if doc.tenant_id == tenant_id]
        if source_type:
            rows = [doc for doc in rows if doc.source_type == source_type]
        if status:
            rows = [doc for doc in rows if doc.status == status]
        if search:
            normalized = search.lower()
            rows = [
                doc
                for doc in rows
                if normalized in str(doc.title).lower()
                or normalized in str(doc.file_name or "").lower()
                or normalized in str((doc.metadata_json or {}).get("url") or "").lower()
            ]
        if tag:
            normalized_tag = tag.lower()
            rows = [
                doc
                for doc in rows
                if normalized_tag in [str(item).lower() for item in (doc.metadata_json or {}).get("tags", [])]
            ]
        if unused_only:
            rows = [
                doc
                for doc in rows
                if not bool((doc.metadata_json or {}).get("used_in_traces"))
            ]
        rows.sort(key=lambda doc: doc.updated_at, reverse=True)
        total = len(rows)
        start = (max(1, page) - 1) * max(1, page_size)
        end = start + max(1, page_size)
        return [(row, len(self.chunks.get(str(row.id), []))) for row in rows[start:end]], total

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
    def run_ingestion_job(cls, tenant_id: str, job_id: str):
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

    def update_document_metadata(self, row, metadata_json: dict):
        row.metadata_json = metadata_json
        row.updated_at = datetime.now(UTC)
        return row

    def set_enabled_in_retrieval(self, row, enabled: bool):
        row.enabled_in_retrieval = enabled
        row.updated_at = datetime.now(UTC)
        return row

    async def create_website_snapshot(self, tenant_id: str, user_id: str, url: str, title: str | None, enabled_in_retrieval: bool, tags=None):
        document_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        row = SimpleNamespace(
            id=document_id,
            tenant_id=tenant_id,
            title=title or "Snapshot",
            source_type="website_snapshot",
            mime_type="text/plain",
            file_name="snapshot.txt",
            storage_path=f"data/documents/{tenant_id}/{document_id}/snapshot.txt",
            status="processing",
            enabled_in_retrieval=enabled_in_retrieval,
            checksum="checksum",
            created_by=user_id,
            approved_by=None,
            created_at=now,
            updated_at=now,
            approved_at=None,
            metadata_json={"url": url, "tags": list(tags or [])},
        )
        FakeAdminRepository.documents[document_id] = row
        FakeAdminRepository.chunks[document_id] = []
        return row, str(uuid.uuid4())


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
    monkeypatch.setattr(admin_module, "_schedule_document_ingestion", lambda background_tasks, tenant_id, job_id: None)

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
        payload = r_list.json()
        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["page"] == 1
        assert payload["page_size"] == 50

        r_page = client.get("/api/v1/admin/documents?page=1&page_size=1")
        assert r_page.status_code == 200
        paged = r_page.json()
        assert paged["total"] == 1
        assert len(paged["items"]) == 1

        r_get = client.get(f"/api/v1/admin/documents/{document_id}")
        assert r_get.status_code == 200
        assert len(r_get.json()["chunks"]) == 1

        r_patch = client.patch(
            f"/api/v1/admin/documents/{document_id}",
            json={"metadata_json": {"category": "policy", "tags": ["security", "ops"]}},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["metadata_json"]["tags"] == ["security", "ops"]

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


def test_update_document_schedules_ingestion_after_reenable(monkeypatch):
    from app.api.v1 import admin as admin_module

    FakeAdminRepository.reset()
    now = datetime.now(UTC)
    doc_id = str(uuid.uuid4())
    FakeAdminRepository.documents[doc_id] = SimpleNamespace(
        id=doc_id,
        tenant_id="tenant-1",
        title="Policy",
        source_type="upload",
        mime_type="text/plain",
        file_name="policy.txt",
        storage_path="data/documents/tenant-1/policy.txt",
        status="approved",
        enabled_in_retrieval=False,
        checksum="checksum",
        created_by="admin-1",
        approved_by="admin-1",
        created_at=now,
        updated_at=now,
        approved_at=now,
        metadata_json={},
    )
    FakeAdminRepository.chunks[doc_id] = []
    scheduled: list[tuple[str, str]] = []

    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module, "DocumentService", FakeDocumentService)
    monkeypatch.setattr(
        admin_module,
        "_schedule_document_ingestion",
        lambda background_tasks, tenant_id, job_id: scheduled.append((tenant_id, job_id)),
    )

    app.dependency_overrides[require_admin] = _ctx_override
    app.dependency_overrides[db_dep] = _db_override
    client = TestClient(app)

    try:
        response = client.patch(
            f"/api/v1/admin/documents/{doc_id}",
            json={"enabled_in_retrieval": True},
        )
        assert response.status_code == 200
        assert response.json()["enabled_in_retrieval"] is True
        assert scheduled == []
    finally:
        app.dependency_overrides.clear()


def test_update_document_with_metadata_and_toggle_is_atomic_on_toggle_failure(monkeypatch):
    from app.api.v1 import admin as admin_module

    class TxAdminRepository(FakeAdminRepository):
        pending_updates: dict[str, dict] = {}

        @classmethod
        def reset(cls):
            super().reset()
            cls.pending_updates = {}

        @classmethod
        def apply_pending(cls):
            for doc_id, payload in list(cls.pending_updates.items()):
                row = cls.documents.get(doc_id)
                if row is None:
                    continue
                for key, value in payload.items():
                    setattr(row, key, value)
                row.updated_at = datetime.now(UTC)
            cls.pending_updates = {}

        @classmethod
        def clear_pending(cls):
            cls.pending_updates = {}

        def update_document(self, row, payload: dict, auto_commit: bool = True):
            if auto_commit:
                return super().update_document(row, payload, auto_commit=auto_commit)
            self.pending_updates[str(row.id)] = dict(payload)
            return row

    class TxDb:
        def commit(self):
            TxAdminRepository.apply_pending()
            return None

        def rollback(self):
            TxAdminRepository.clear_pending()
            return None

        def refresh(self, row):
            return row

    class FailingToggleService(FakeDocumentService):
        def set_enabled_in_retrieval(self, row, enabled: bool):
            self.db.rollback()
            raise HTTPException(status_code=502, detail="toggle failed")

    def _tx_db_override():
        return TxDb()

    TxAdminRepository.reset()
    now = datetime.now(UTC)
    doc_id = str(uuid.uuid4())
    TxAdminRepository.documents[doc_id] = SimpleNamespace(
        id=doc_id,
        tenant_id="tenant-1",
        title="Policy",
        source_type="upload",
        mime_type="text/plain",
        file_name="policy.txt",
        storage_path="data/documents/tenant-1/policy.txt",
        status="approved",
        enabled_in_retrieval=True,
        checksum="checksum",
        created_by="admin-1",
        approved_by="admin-1",
        created_at=now,
        updated_at=now,
        approved_at=now,
        metadata_json={"category": "old"},
    )
    TxAdminRepository.chunks[doc_id] = []

    monkeypatch.setattr(admin_module, "AdminRepository", TxAdminRepository)
    monkeypatch.setattr(admin_module, "DocumentService", FailingToggleService)
    monkeypatch.setattr(admin_module, "_schedule_document_ingestion", lambda background_tasks, tenant_id, job_id: None)

    app.dependency_overrides[require_admin] = _ctx_override
    app.dependency_overrides[db_dep] = _tx_db_override
    client = TestClient(app)

    try:
        response = client.patch(
            f"/api/v1/admin/documents/{doc_id}",
            json={"enabled_in_retrieval": False, "metadata_json": {"category": "new"}},
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "toggle failed"

        row = TxAdminRepository.documents[doc_id]
        assert row.metadata_json == {"category": "old"}
        assert row.enabled_in_retrieval is True
        assert TxAdminRepository.pending_updates == {}
    finally:
        app.dependency_overrides.clear()


def test_list_documents_supports_unused_only_filter(monkeypatch):
    from app.api.v1 import admin as admin_module

    FakeAdminRepository.reset()
    now = datetime.now(UTC)
    unused_id = str(uuid.uuid4())
    used_id = str(uuid.uuid4())
    FakeAdminRepository.documents[unused_id] = SimpleNamespace(
        id=unused_id,
        tenant_id="tenant-1",
        title="Unused document",
        source_type="upload",
        mime_type="text/plain",
        file_name="unused.txt",
        storage_path="data/documents/tenant-1/unused.txt",
        status="approved",
        enabled_in_retrieval=True,
        checksum="checksum",
        created_by="admin-1",
        approved_by="admin-1",
        created_at=now,
        updated_at=now,
        approved_at=now,
        metadata_json={"used_in_traces": False},
    )
    FakeAdminRepository.documents[used_id] = SimpleNamespace(
        id=used_id,
        tenant_id="tenant-1",
        title="Used document",
        source_type="upload",
        mime_type="text/plain",
        file_name="used.txt",
        storage_path="data/documents/tenant-1/used.txt",
        status="approved",
        enabled_in_retrieval=True,
        checksum="checksum",
        created_by="admin-1",
        approved_by="admin-1",
        created_at=now,
        updated_at=now,
        approved_at=now,
        metadata_json={"used_in_traces": True},
    )

    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module, "DocumentService", FakeDocumentService)
    monkeypatch.setattr(admin_module, "_schedule_document_ingestion", lambda background_tasks, tenant_id, job_id: None)

    app.dependency_overrides[require_admin] = _ctx_override
    app.dependency_overrides[db_dep] = _db_override
    client = TestClient(app)
    try:
        response = client.get("/api/v1/admin/documents?unused_only=true")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["items"][0]["id"] == unused_id
    finally:
        app.dependency_overrides.clear()
