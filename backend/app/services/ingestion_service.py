import io
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document, DocumentChunk, IngestionJob, KnowledgeBase


def extract_text(data: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        try:
            return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)
        except Exception as exc:
            raise ValueError("invalid_pdf") from exc
    return data.decode("utf-8", errors="replace")


def add_text_chunks(db: Session, document: Document, text: str, size: int, overlap: int) -> int:
    overlap = min(overlap, size - 1); count = 0
    for index, start in enumerate(range(0, len(text), size - overlap)):
        chunk = text[start:start + size]
        db.add(DocumentChunk(document_id=document.id, chunk_index=index, content=chunk, token_count=max(1, len(chunk) // 4)))
        count += 1
    return count


def replace_chunks(db: Session, document: Document, data: bytes, suffix: str) -> int:
    text = extract_text(data, suffix)
    if not text.strip():
        raise ValueError("document_has_no_text")
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    kb = db.get(KnowledgeBase, document.knowledge_base_id)
    config = get_settings(); size = kb.chunk_size_chars if kb else config.document_chunk_size_chars
    overlap = min(kb.chunk_overlap_chars if kb else config.document_chunk_overlap_chars, size - 1)
    return add_text_chunks(db, document, text, size, overlap)


def finish_upload_job(db: Session, document: Document, job: IngestionJob) -> int:
    if not document.storage_path:
        raise ValueError("document_file_missing")
    path = Path(document.storage_path)
    if not path.is_file():
        raise ValueError("document_file_missing")
    count = replace_chunks(db, document, path.read_bytes(), path.suffix.lower())
    publication_mode = document.metadata_json.get("publication_mode", "manual")
    document.status = "approved" if publication_mode == "automatic" else "ready"
    document.approved_at = datetime.now(timezone.utc) if document.status == "approved" else None
    job.status = "completed"
    job.error_code = None
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return count


def recover_interrupted_uploads(db: Session) -> int:
    jobs = list(db.scalars(select(IngestionJob).where(IngestionJob.kind == "upload", IngestionJob.status.in_(["queued", "processing"]))))
    recovered = 0
    for job in jobs:
        document = db.get(Document, job.document_id) if job.document_id else None
        if not document:
            job.status = "failed"; job.error_code = "document_missing"; continue
        job.status = "processing"; job.attempts += 1
        try:
            finish_upload_job(db, document, job); recovered += 1
        except Exception as exc:
            db.rollback()
            job = db.get(IngestionJob, job.id); document = db.get(Document, job.document_id) if job else None
            if job: job.status = "failed"; job.error_code = type(exc).__name__; job.updated_at = datetime.now(timezone.utc)
            if document: document.status = "failed"
            db.commit()
    db.commit()
    return recovered
