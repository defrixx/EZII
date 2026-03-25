from __future__ import annotations

from datetime import UTC, datetime
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
        self.upserts = []

    def delete_by_field(self, field: str, value: str):
        self.deleted.append((field, value))

    def upsert_entry(self, point_id: str, tenant_id: str, vector: list[float], payload: dict):
        self.upserts.append(
            {
                "point_id": point_id,
                "tenant_id": tenant_id,
                "vector": vector,
                "payload": payload,
            }
        )


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
    assert service.vector.deleted == [("document_id", document.id)]
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
    assert service.vector.deleted == [("document_id", document.id)]
    assert len(service.vector.upserts) == 1
    assert service.vector.upserts[0]["payload"]["status"] == "approved"
    assert service.vector.upserts[0]["payload"]["source_type"] == "document"


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
