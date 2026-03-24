from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.models import (
    AllowlistDomain,
    AuditLog,
    Document,
    DocumentChunk,
    DocumentIngestionJob,
    ErrorLog,
    ProviderSetting,
    ResponseTrace,
)


class AdminRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_allowlist(self, tenant_id: str) -> list[AllowlistDomain]:
        stmt = select(AllowlistDomain).where(AllowlistDomain.tenant_id == tenant_id).order_by(AllowlistDomain.domain.asc())
        return list(self.db.scalars(stmt))

    def list_documents(
        self,
        tenant_id: str,
        source_type: str | None = None,
        status: str | None = None,
    ) -> list[tuple[Document, int]]:
        stmt = (
            select(Document, func.count(DocumentChunk.id))
            .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(Document.tenant_id == tenant_id)
        )
        if source_type:
            stmt = stmt.where(Document.source_type == source_type)
        if status:
            stmt = stmt.where(Document.status == status)
        stmt = stmt.group_by(Document.id).order_by(Document.updated_at.desc(), Document.created_at.desc())
        return list(self.db.execute(stmt).all())

    def get_document(self, tenant_id: str, document_id: str) -> Document | None:
        stmt = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
        return self.db.scalar(stmt)

    def get_document_with_chunk_count(self, tenant_id: str, document_id: str) -> tuple[Document, int] | None:
        stmt = (
            select(Document, func.count(DocumentChunk.id))
            .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(Document.id == document_id, Document.tenant_id == tenant_id)
            .group_by(Document.id)
        )
        return self.db.execute(stmt).one_or_none()

    def list_document_chunks(self, tenant_id: str, document_id: str) -> list[DocumentChunk]:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(self.db.scalars(stmt))

    def create_document(self, payload: dict, auto_commit: bool = True) -> Document:
        row = Document(**payload)
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def update_document(self, row: Document, payload: dict, auto_commit: bool = True) -> Document:
        for key, value in payload.items():
            setattr(row, key, value)
        if "updated_at" not in payload:
            row.updated_at = datetime.now(timezone.utc)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def replace_document_chunks(self, tenant_id: str, document_id: str, chunks: list[dict], auto_commit: bool = True) -> list[DocumentChunk]:
        self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id)
        )
        rows = [DocumentChunk(tenant_id=tenant_id, document_id=document_id, **chunk) for chunk in chunks]
        self.db.add_all(rows)
        if auto_commit:
            self.db.commit()
            for row in rows:
                self.db.refresh(row)
        else:
            self.db.flush()
        return rows

    def delete_document(self, row: Document, auto_commit: bool = True) -> None:
        self.db.execute(delete(DocumentIngestionJob).where(DocumentIngestionJob.document_id == row.id))
        self.db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == row.id))
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()

    def create_document_ingestion_job(self, payload: dict, auto_commit: bool = True) -> DocumentIngestionJob:
        row = DocumentIngestionJob(**payload)
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get_document_ingestion_job(self, tenant_id: str, job_id: str) -> DocumentIngestionJob | None:
        stmt = select(DocumentIngestionJob).where(
            DocumentIngestionJob.id == job_id,
            DocumentIngestionJob.tenant_id == tenant_id,
        )
        return self.db.scalar(stmt)

    def get_document_ingestion_job_by_id(self, job_id: str) -> DocumentIngestionJob | None:
        stmt = select(DocumentIngestionJob).where(DocumentIngestionJob.id == job_id)
        return self.db.scalar(stmt)

    def get_latest_document_ingestion_job(self, tenant_id: str, document_id: str) -> DocumentIngestionJob | None:
        stmt = (
            select(DocumentIngestionJob)
            .where(
                DocumentIngestionJob.tenant_id == tenant_id,
                DocumentIngestionJob.document_id == document_id,
            )
            .order_by(DocumentIngestionJob.created_at.desc())
        )
        return self.db.scalar(stmt)

    def update_document_ingestion_job(
        self,
        row: DocumentIngestionJob,
        payload: dict,
        auto_commit: bool = True,
    ) -> DocumentIngestionJob:
        for key, value in payload.items():
            setattr(row, key, value)
        if "updated_at" not in payload:
            row.updated_at = datetime.now(timezone.utc)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def create_allowlist(self, tenant_id: str, domain: str, notes: str | None, enabled: bool) -> AllowlistDomain:
        row = AllowlistDomain(tenant_id=tenant_id, domain=domain, notes=notes, enabled=enabled)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_allowlist(
        self,
        tenant_id: str,
        domain_id: str,
        domain: str | None = None,
        notes: str | None = None,
        enabled: bool | None = None,
    ) -> AllowlistDomain | None:
        row = self.db.scalar(
            select(AllowlistDomain).where(AllowlistDomain.id == domain_id, AllowlistDomain.tenant_id == tenant_id)
        )
        if not row:
            return None
        if domain is not None:
            row.domain = domain
        if notes is not None:
            row.notes = notes
        if enabled is not None:
            row.enabled = enabled
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_allowlist(self, tenant_id: str, domain_id: str) -> bool:
        row = self.db.scalar(
            select(AllowlistDomain).where(AllowlistDomain.id == domain_id, AllowlistDomain.tenant_id == tenant_id)
        )
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def get_provider(self, tenant_id: str) -> ProviderSetting | None:
        stmt = select(ProviderSetting).where(ProviderSetting.tenant_id == tenant_id)
        return self.db.scalar(stmt)

    def upsert_provider(self, tenant_id: str, payload: dict) -> ProviderSetting:
        data = dict(payload)
        api_key = data.get("api_key")
        if api_key:
            data["api_key"] = encrypt_secret(str(api_key))
        row = self.get_provider(tenant_id)
        if row:
            for k, v in data.items():
                setattr(row, k, v)
        else:
            row = ProviderSetting(tenant_id=tenant_id, **data)
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    @staticmethod
    def provider_api_key_plain(row: ProviderSetting | None) -> str:
        if row is None:
            return ""
        return decrypt_secret(str(row.api_key or ""))

    def add_audit_log(self, tenant_id: str, user_id: str, action: str, entity_type: str, entity_id: str, payload: dict):
        row = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        self.db.add(row)
        self.db.commit()

    def add_error_log(self, tenant_id: str, user_id: str | None, chat_id: str | None, error_type: str, message: str, metadata: dict):
        row = ErrorLog(
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            error_type=error_type,
            message=message,
            metadata_json=metadata,
        )
        self.db.add(row)
        self.db.commit()

    def add_trace(self, payload: dict) -> ResponseTrace:
        row = ResponseTrace(**payload)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_error_logs(self, tenant_id: str, limit: int = 100) -> list[ErrorLog]:
        stmt = select(ErrorLog).where(ErrorLog.tenant_id == tenant_id).order_by(ErrorLog.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def list_traces(self, tenant_id: str, limit: int = 100) -> list[ResponseTrace]:
        stmt = (
            select(ResponseTrace)
            .where(ResponseTrace.tenant_id == tenant_id)
            .order_by(ResponseTrace.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
