from __future__ import annotations

from datetime import UTC, datetime
import asyncio
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from app.services.document_service import DocumentService


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        self.flushes += 1

    def refresh(self, row):
        return row


class FakeRepo:
    def __init__(self, document, job):
        self.document = document
        self.job = job
        self.jobs: dict[str, object] = {str(job.id): job}
        self.documents = {str(document.id): document}
        self.chunk_rows = []
        self.error_logs = []
        self.audit_logs = []

    def get_document_ingestion_job_by_id(self, job_id: str):
        return self.jobs.get(job_id)

    def claim_document_ingestion_job(self, job_id: str, *, running_stale_after_s: int = 300):
        job = self.jobs.get(job_id)
        if not job:
            return None
        if job.status not in {"pending", "running"}:
            return None
        job.status = "running"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.finished_at = None
        self.jobs[job_id] = job
        self.job = job
        return job

    def get_document(self, tenant_id: str, document_id: str):
        row = self.documents.get(document_id)
        if row and str(row.tenant_id) == tenant_id:
            return row
        return None

    def update_document_ingestion_job(self, job, payload: dict, auto_commit: bool = True):
        for key, value in payload.items():
            setattr(job, key, value)
        self.jobs[str(job.id)] = job
        return job

    def update_document(self, row, payload: dict, auto_commit: bool = True):
        for key, value in payload.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(UTC)
        self.documents[str(row.id)] = row
        return row

    def replace_document_chunks(self, tenant_id: str, document_id: str, chunks_payload: list[dict], auto_commit: bool = True):
        self.chunk_rows = []
        now = datetime.now(UTC)
        for chunk in chunks_payload:
            row = SimpleNamespace(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=chunk["chunk_index"],
                content=chunk["content"],
                token_count=chunk["token_count"],
                embedding_model=chunk["embedding_model"],
                metadata_json=chunk["metadata_json"],
                created_at=now,
            )
            self.chunk_rows.append(row)
        return list(self.chunk_rows)

    def list_document_chunks(self, tenant_id: str, document_id: str):
        return list(self.chunk_rows)

    def add_error_log(self, **payload):
        self.error_logs.append(payload)

    def add_audit_log(self, *args, **kwargs):
        self.audit_logs.append((args, kwargs))


class FakeVector:
    def __init__(self):
        self.deleted = []
        self.deleted_by_filters = []
        self.upserts = []
        self.upsert_batches = []

    def delete_by_field(self, field: str, value: str, tenant_id: str | None = None):
        self.deleted.append((field, value, tenant_id))

    def upsert_entry(self, point_id: str, tenant_id: str, vector: list[float], payload: dict):
        self.upserts.append(
            {
                "point_id": point_id,
                "tenant_id": tenant_id,
                "vector": vector,
                "payload": payload,
            }
        )

    def upsert_entries(self, entries: list[dict]):
        self.upsert_batches.append(entries)
        for item in entries:
            self.upserts.append(
                {
                    "point_id": item["id"],
                    "tenant_id": item["payload"]["tenant_id"],
                    "vector": item["vector"],
                    "payload": item["payload"],
                }
            )

    def delete_by_filters(self, *, tenant_id: str, must: dict | None = None, must_not: dict | None = None):
        self.deleted_by_filters.append((tenant_id, must or {}, must_not or {}))


class FakeProvider:
    embedding_model = "test-embedding-model"

    async def embeddings(self, inputs: list[str]):
        return [[0.1, 0.2, 0.3] for _ in inputs]


def _make_document(tmp_path: Path, *, mime_type: str = "text/plain", enabled: bool = True, file_name: str = "doc.txt"):
    document_id = str(uuid.uuid4())
    storage_path = tmp_path / document_id / file_name
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        id=document_id,
        tenant_id="tenant-1",
        title="Internal Policy",
        source_type="upload",
        mime_type=mime_type,
        file_name=file_name,
        storage_path=str(storage_path),
        status="processing",
        enabled_in_retrieval=enabled,
        checksum="checksum",
        created_by="admin-1",
        approved_by=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        approved_at=None,
        metadata_json={"category": "policy"},
    )


def _make_job(document):
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        tenant_id=document.tenant_id,
        document_id=document.id,
        status="pending",
        attempt_count=0,
        triggered_by="admin-1",
        metadata_json={"reason": "upload"},
        error_message=None,
        started_at=None,
        finished_at=None,
    )


def _make_service(document, job, tmp_path: Path):
    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.settings = SimpleNamespace(
        document_chunk_size_chars=120,
        document_chunk_overlap_chars=30,
        document_storage_dir=str(tmp_path),
    )
    service.repo = FakeRepo(document, job)
    service.retrieval = SimpleNamespace(_provider_for_tenant=lambda tenant_id: FakeProvider())
    service.vector = FakeVector()
    return service


def test_process_job_creates_chunks_and_syncs_qdrant(tmp_path):
    document = _make_document(tmp_path)
    storage_path = Path(document.storage_path)
    storage_path.write_text(
        "OPERATIONS\n\nAll expenses require manager approval.\n\nReceipts must be uploaded within 10 days.",
        encoding="utf-8",
    )
    job = _make_job(document)
    service = _make_service(document, job, tmp_path)

    service.process_job(str(job.id))

    assert service.repo.job.status == "completed"
    assert service.repo.document.status == "draft"
    assert service.repo.document.approved_by is None
    assert len(service.repo.chunk_rows) >= 1
    assert service.repo.chunk_rows[0].embedding_model == "test-embedding-model"
    assert service.vector.deleted == [("document_id", document.id, document.tenant_id)]
    assert service.vector.upserts == []


def test_approve_document_publishes_existing_chunks(tmp_path):
    document = _make_document(tmp_path)
    document.status = "draft"
    job = _make_job(document)
    service = _make_service(document, job, tmp_path)
    service.repo.chunk_rows = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            tenant_id=document.tenant_id,
            document_id=document.id,
            chunk_index=0,
            content="All expenses require manager approval.",
            token_count=5,
            embedding_model="test-embedding-model",
            metadata_json={"section": "OPERATIONS"},
            created_at=datetime.now(UTC),
        )
    ]

    approved = service.approve_document(document, "admin-2")

    assert approved.status == "approved"
    assert approved.approved_by == "admin-2"
    assert service.vector.deleted == []
    assert len(service.vector.deleted_by_filters) == 1
    tenant_id, must, must_not = service.vector.deleted_by_filters[0]
    assert tenant_id == document.tenant_id
    assert must["document_id"] == document.id
    assert "publish_token" in must_not
    assert len(service.vector.upserts) == 1
    assert service.vector.upserts[0]["payload"]["status"] == "approved"
    assert service.vector.upserts[0]["payload"]["source_type"] == "upload"
    assert "publish_token" in service.vector.upserts[0]["payload"]


def test_process_job_marks_failed_when_parsing_fails(tmp_path):
    document = _make_document(tmp_path, mime_type="application/octet-stream", file_name="broken.bin")
    Path(document.storage_path).write_bytes(b"\x00\x01\x02broken")
    job = _make_job(document)
    service = _make_service(document, job, tmp_path)

    service.process_job(str(job.id))

    assert service.repo.job.status == "failed"
    assert service.repo.document.status == "failed"
    assert service.db.rollbacks == 1
    assert service.repo.error_logs
    assert "document_id" in service.repo.error_logs[0]["metadata"]
    assert service.vector.upserts == []


def test_create_upload_rejects_files_larger_than_limit(tmp_path):
    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.settings = SimpleNamespace(
        document_upload_max_bytes=50 * 1024 * 1024,
        document_storage_dir=str(tmp_path),
    )
    service.repo = SimpleNamespace(create_document=lambda *args, **kwargs: None)

    class OversizedUpload:
        filename = "large.pdf"
        content_type = "application/pdf"

        async def read(self):
            return b"x" * (50 * 1024 * 1024 + 1)

    class Payload:
        title = "Large PDF"
        enabled_in_retrieval = True
        metadata_json = {}

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        import asyncio

        asyncio.run(service.create_upload("tenant-1", "admin-1", OversizedUpload(), Payload()))

    assert exc.value.status_code == 413
    assert "50 MB" in str(exc.value.detail)


def test_extract_blocks_accepts_only_pdf_md_txt():
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        DocumentService.extract_blocks(b"hello", "text/csv", "sheet.csv")


def test_approve_document_preserves_existing_retrieval_flag(tmp_path):
    document = _make_document(tmp_path, enabled=False)
    document.status = "draft"
    job = _make_job(document)
    service = _make_service(document, job, tmp_path)
    service.repo.chunk_rows = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            tenant_id=document.tenant_id,
            document_id=document.id,
            chunk_index=0,
            content="Policy text",
            token_count=2,
            embedding_model="test-embedding-model",
            metadata_json={},
            created_at=datetime.now(UTC),
        )
    ]

    approved = service.approve_document(document, "admin-2")

    assert approved.status == "approved"
    assert approved.enabled_in_retrieval is False
    assert service.vector.upserts == []


def test_approve_document_fails_closed_when_embeddings_fail(tmp_path):
    document = _make_document(tmp_path, enabled=True)
    document.status = "draft"
    job = _make_job(document)
    service = _make_service(document, job, tmp_path)
    service.repo.chunk_rows = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            tenant_id=document.tenant_id,
            document_id=document.id,
            chunk_index=0,
            content="Policy text",
            token_count=2,
            embedding_model="test-embedding-model",
            metadata_json={},
            created_at=datetime.now(UTC),
        )
    ]

    class FailingProvider:
        embedding_model = "test-embedding-model"

        async def embeddings(self, inputs: list[str]):
            raise RuntimeError("provider down")

    service.retrieval = SimpleNamespace(_provider_for_tenant=lambda tenant_id: FailingProvider())

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        service.approve_document(document, "admin-2")

    assert exc.value.status_code == 502
    assert document.status == "draft"
    assert service.vector.deleted == []
    assert service.vector.upserts == []


def test_set_enabled_in_retrieval_republishes_approved_document_without_reset(tmp_path):
    document = _make_document(tmp_path, enabled=False)
    document.status = "approved"
    document.approved_by = "admin-2"
    document.approved_at = datetime.now(UTC)
    job = _make_job(document)
    service = _make_service(document, job, tmp_path)
    service.repo.chunk_rows = [
        SimpleNamespace(
            id=str(uuid.uuid4()),
            tenant_id=document.tenant_id,
            document_id=document.id,
            chunk_index=0,
            content="Policy text",
            token_count=2,
            embedding_model="test-embedding-model",
            metadata_json={},
            created_at=datetime.now(UTC),
        )
    ]

    updated = service.set_enabled_in_retrieval(document, True)
    assert updated.status == "approved"
    assert updated.enabled_in_retrieval is True
    assert len(service.vector.upserts) == 1


def test_create_upload_rejects_unsupported_type_before_persisting(tmp_path):
    class FakeRepo:
        def __init__(self):
            self.create_document_called = False

        def create_document(self, payload: dict, auto_commit: bool = True):
            self.create_document_called = True
            raise AssertionError("create_document must not be called for unsupported files")

    class Upload:
        filename = "table.csv"
        content_type = "text/csv"

        async def read(self):
            return b"term,definition\nx,y\n"

    class Payload:
        title = "Table"
        enabled_in_retrieval = True
        metadata_json = {}

    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.settings = SimpleNamespace(
        document_upload_max_bytes=50 * 1024 * 1024,
        document_storage_dir=str(tmp_path),
    )
    service.repo = FakeRepo()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.create_upload("tenant-1", "admin-1", Upload(), Payload()))

    assert exc.value.status_code == 400
    assert service.repo.create_document_called is False
    assert list(tmp_path.rglob("*")) == []


def test_fetch_snapshot_rejects_cross_domain_redirect(monkeypatch, tmp_path):
    service = DocumentService.__new__(DocumentService)
    service._assert_public_snapshot_host = lambda url: "example.com" if "example.com" in url else "evil.example"
    service._resolve_public_ips_sync = lambda host: {"93.184.216.34"}
    service._response_peer_ip = lambda response: "93.184.216.34"

    class DummyResponse:
        status_code = 302
        headers = {"location": "https://evil.example/path"}
        url = "https://example.com/page"
        text = "<html><body>body</body></html>"

        def raise_for_status(self):
            return None

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return DummyResponse()

    monkeypatch.setattr("app.services.document_service.httpx.AsyncClient", lambda timeout=15, follow_redirects=False: DummyClient())

    document = SimpleNamespace(
        title="Snapshot",
        file_name="snapshot.txt",
        mime_type="text/plain",
        metadata_json={"url": "https://example.com/page", "domain": "example.com"},
    )

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(service._fetch_snapshot_bytes(document))

    assert "same domain" in str(exc.value).lower()


def test_fetch_snapshot_rejects_subdomain_redirect(monkeypatch):
    service = DocumentService.__new__(DocumentService)
    service._assert_public_snapshot_host = lambda url: "example.com" if "example.com" in url else "sub.example.com"
    service._resolve_public_ips_sync = lambda host: {"93.184.216.34"}
    service._response_peer_ip = lambda response: "93.184.216.34"

    class DummyResponse:
        status_code = 302
        headers = {"location": "https://sub.example.com/path"}
        url = "https://example.com/page"
        text = "<html><body>body</body></html>"

        def raise_for_status(self):
            return None

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return DummyResponse()

    monkeypatch.setattr("app.services.document_service.httpx.AsyncClient", lambda timeout=15, follow_redirects=False: DummyClient())

    document = SimpleNamespace(
        title="Snapshot",
        file_name="snapshot.txt",
        mime_type="text/plain",
        metadata_json={"url": "https://example.com/page", "domain": "example.com"},
    )

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(service._fetch_snapshot_bytes(document))

    assert "same domain" in str(exc.value).lower()


def test_create_website_snapshot_persists_txt_metadata(tmp_path):
    created_payload: dict | None = None
    updated_payload: dict | None = None

    class FakeRepoSnapshot:
        def create_document(self, payload: dict, auto_commit: bool = True):
            nonlocal created_payload
            created_payload = dict(payload)
            return SimpleNamespace(id=str(uuid.uuid4()), **payload)

        def update_document(self, row, payload: dict, auto_commit: bool = True):
            nonlocal updated_payload
            updated_payload = dict(payload)
            for key, value in payload.items():
                setattr(row, key, value)
            return row

        def create_document_ingestion_job(self, payload: dict, auto_commit: bool = True):
            return SimpleNamespace(id=str(uuid.uuid4()), **payload)

    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.settings = SimpleNamespace(document_storage_dir=str(tmp_path))
    service.repo = FakeRepoSnapshot()
    service._assert_public_snapshot_host = lambda url: "example.com"

    row, _ = asyncio.run(
        service.create_website_snapshot(
            tenant_id="tenant-1",
            user_id="admin-1",
            url="https://example.com/docs",
            title=None,
            enabled_in_retrieval=True,
            tags=["security"],
        )
    )

    assert created_payload is not None
    assert created_payload["mime_type"] == "text/plain"
    assert created_payload["file_name"] == "snapshot.txt"
    assert updated_payload is not None
    assert str(updated_payload["storage_path"]).endswith("/snapshot.txt")
    assert row.file_name == "snapshot.txt"


def test_recover_pending_jobs_processes_each_job(monkeypatch):
    jobs = [SimpleNamespace(id="job-1"), SimpleNamespace(id="job-2")]

    class FakeSessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeRecoveryRepo:
        def __init__(self, db):
            self.db = db

        def list_recoverable_document_ingestion_jobs(self, limit: int = 50, running_stale_after_s: int = 300):
            return jobs

    processed: list[str] = []

    monkeypatch.setattr("app.services.document_service.SessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr("app.services.document_service.AdminRepository", FakeRecoveryRepo)
    monkeypatch.setattr(DocumentService, "__init__", lambda self, db: None)
    monkeypatch.setattr(DocumentService, "process_job", lambda self, job_id: processed.append(job_id))

    recovered = DocumentService.recover_pending_jobs(limit=10, running_stale_after_s=30)

    assert recovered == 2
    assert processed == ["job-1", "job-2"]


def test_delete_document_restores_file_if_vector_delete_fails(tmp_path):
    storage_file = tmp_path / "tenant-1" / "doc-1" / "doc.txt"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text("policy", encoding="utf-8")
    document = SimpleNamespace(id="doc-1", tenant_id="tenant-1", storage_path=str(storage_file))

    class FailingVector:
        def delete_by_field(self, field: str, value: str, tenant_id: str | None = None):
            raise RuntimeError("qdrant unavailable")

    class TrackingRepo:
        def __init__(self):
            self.deleted = False

        def delete_document(self, row, auto_commit: bool = True):
            self.deleted = True

    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.repo = TrackingRepo()
    service.vector = FailingVector()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        service.delete_document(document)

    assert exc.value.status_code == 502
    assert service.repo.deleted is False
    assert storage_file.exists()


def test_delete_document_removes_file_and_db_row_on_success(tmp_path):
    storage_file = tmp_path / "tenant-1" / "doc-2" / "doc.txt"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text("policy", encoding="utf-8")
    document = SimpleNamespace(id="doc-2", tenant_id="tenant-1", storage_path=str(storage_file))

    class TrackingVector:
        def __init__(self):
            self.calls = []

        def delete_by_field(self, field: str, value: str, tenant_id: str | None = None):
            self.calls.append((field, value, tenant_id))

    class TrackingRepo:
        def __init__(self):
            self.deleted = False

        def delete_document(self, row, auto_commit: bool = True):
            self.deleted = True

    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.repo = TrackingRepo()
    service.vector = TrackingVector()

    service.delete_document(document)

    assert service.repo.deleted is True
    assert service.db.commits == 1
    assert service.vector.calls == [("document_id", "doc-2", "tenant-1")]
    assert not storage_file.exists()


def test_process_job_keeps_completed_status_when_audit_log_fails(tmp_path):
    document = _make_document(tmp_path)
    storage_path = Path(document.storage_path)
    storage_path.write_text("Expense approvals are required.", encoding="utf-8")
    job = _make_job(document)
    service = _make_service(document, job, tmp_path)

    def _raise_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    service.repo.add_audit_log = _raise_audit

    service.process_job(str(job.id))

    assert service.repo.job.status == "completed"
    assert service.repo.document.status == "draft"
    assert service.db.rollbacks == 0


def test_delete_document_returns_success_when_storage_cleanup_fails(tmp_path):
    storage_file = tmp_path / "tenant-1" / "doc-3" / "doc.txt"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text("policy", encoding="utf-8")
    document = SimpleNamespace(id="doc-3", tenant_id="tenant-1", storage_path=str(storage_file))

    class TrackingVector:
        def __init__(self):
            self.calls = []

        def delete_by_field(self, field: str, value: str, tenant_id: str | None = None):
            self.calls.append((field, value, tenant_id))

    class TrackingRepo:
        def __init__(self):
            self.deleted = False

        def delete_document(self, row, auto_commit: bool = True):
            self.deleted = True

    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.repo = TrackingRepo()
    service.vector = TrackingVector()
    service._delete_storage_file_strict = lambda path: (_ for _ in ()).throw(RuntimeError("fs cleanup failed"))

    service.delete_document(document)

    assert service.repo.deleted is True
    assert service.db.commits == 1
    assert service.vector.calls == [("document_id", "doc-3", "tenant-1")]


def test_delete_document_enqueues_storage_cleanup_retry(tmp_path):
    storage_file = tmp_path / "tenant-1" / "doc-4" / "doc.txt"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text("policy", encoding="utf-8")
    document = SimpleNamespace(id="doc-4", tenant_id="tenant-1", storage_path=str(storage_file))

    class TrackingVector:
        def delete_by_field(self, field: str, value: str, tenant_id: str | None = None):
            return None

    class TrackingRepo:
        def __init__(self):
            self.cleanup_tasks = []

        def delete_document(self, row, auto_commit: bool = True):
            return None

        def enqueue_storage_cleanup_task(
            self,
            *,
            tenant_id: str,
            document_id: str,
            storage_path: str,
            error_message: str | None = None,
            auto_commit: bool = True,
        ):
            self.cleanup_tasks.append(
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "storage_path": storage_path,
                    "error_message": error_message or "",
                    "auto_commit": auto_commit,
                }
            )

    service = DocumentService.__new__(DocumentService)
    service.db = FakeDb()
    service.repo = TrackingRepo()
    service.vector = TrackingVector()
    service._delete_storage_file_strict = lambda path: (_ for _ in ()).throw(RuntimeError("fs cleanup failed"))

    service.delete_document(document)

    assert len(service.repo.cleanup_tasks) == 1
    task = service.repo.cleanup_tasks[0]
    assert task["tenant_id"] == "tenant-1"
    assert task["document_id"] == "doc-4"
    assert ".deleting-doc.txt" in task["storage_path"]
    assert "fs cleanup failed" in task["error_message"]


def test_recover_storage_cleanup_queue_purges_old_failed_tasks(monkeypatch):
    calls: dict[str, object] = {}

    class FakeRepo:
        def claim_storage_cleanup_tasks(self, *, limit: int, running_stale_after_s: int):
            calls["claim"] = {"limit": limit, "running_stale_after_s": running_stale_after_s}
            return []

        def complete_storage_cleanup_task(self, row, auto_commit: bool = True):
            return None

        def reschedule_storage_cleanup_task(self, row, *, error_message: str, max_retries: int, base_delay_s: int = 30, auto_commit: bool = True):
            return True

        def purge_failed_storage_cleanup_tasks(self, *, older_than_days: int, limit: int, auto_commit: bool = True):
            calls["gc"] = {"older_than_days": older_than_days, "limit": limit, "auto_commit": auto_commit}
            return 2

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr("app.services.document_service.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("app.services.document_service.AdminRepository", lambda db: FakeRepo())
    monkeypatch.setattr(
        "app.services.document_service.get_settings",
        lambda: SimpleNamespace(storage_cleanup_failed_retention_days=45, storage_cleanup_gc_batch_size=120),
    )

    cleaned = DocumentService.recover_storage_cleanup_queue(limit=10)

    assert cleaned == 0
    assert calls["claim"] == {"limit": 10, "running_stale_after_s": 300}
    assert calls["gc"] == {"older_than_days": 45, "limit": 120, "auto_commit": True}


def test_fetch_snapshot_rejects_non_html_content_type(monkeypatch):
    service = DocumentService.__new__(DocumentService)
    service._assert_public_snapshot_host = lambda url: "example.com"
    service._resolve_public_ips_sync = lambda host: {"93.184.216.34"}
    service._response_peer_ip = lambda response: "93.184.216.34"

    class DummyResponse:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        url = "https://example.com/page"
        content = b"%PDF-1.4"

        def raise_for_status(self):
            return None

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return DummyResponse()

    monkeypatch.setattr("app.services.document_service.httpx.AsyncClient", lambda timeout=15, follow_redirects=False: DummyClient())

    document = SimpleNamespace(
        title="Snapshot",
        file_name="snapshot.txt",
        mime_type="text/plain",
        metadata_json={"url": "https://example.com/page", "domain": "example.com"},
    )

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(service._fetch_snapshot_bytes(document))

    assert "html content" in str(exc.value).lower()
