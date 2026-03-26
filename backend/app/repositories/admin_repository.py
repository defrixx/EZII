from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import String, and_, case, cast, delete, func, literal, or_, select, true, update
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import JSONB
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.models import (
    AuditLog,
    Document,
    DocumentChunk,
    DocumentIngestionJob,
    ErrorLog,
    ProviderSetting,
    ResponseTrace,
    StorageCleanupTask,
)


class AdminRepository:
    _TEXT_FALLBACK_STOPWORDS = {
        "the", "and", "for", "with", "that", "this", "what", "which", "when", "where", "who", "how",
        "about", "into", "from", "your", "you", "are", "is", "was", "were", "can", "could",
        "что", "это", "как", "для", "или", "при", "про", "без", "под", "над", "где", "когда",
        "после", "перед", "если", "чтобы", "какой", "какая", "какие", "такой", "такая", "такие",
        "такое", "мне", "нам", "вам", "они", "она", "оно", "его", "ее", "их", "наш", "ваш",
    }

    def __init__(self, db: Session):
        self.db = db

    def _is_postgres(self) -> bool:
        bind = self.db.get_bind()
        dialect = getattr(bind, "dialect", None)
        return str(getattr(dialect, "name", "")).lower() == "postgresql"

    def _build_documents_filtered_ids_stmt(
        self,
        tenant_id: str,
        source_type: str | None = None,
        status: str | None = None,
        *,
        search: str | None = None,
        tag: str | None = None,
    ):
        filtered_docs_stmt = select(Document.id).where(Document.tenant_id == tenant_id)
        if source_type:
            filtered_docs_stmt = filtered_docs_stmt.where(Document.source_type == source_type)
        if status:
            filtered_docs_stmt = filtered_docs_stmt.where(Document.status == status)

        is_postgres = self._is_postgres()
        if search:
            q = f"%{search.strip()}%"
            if q != "%%":
                search_conditions = [
                    Document.title.ilike(q),
                    Document.file_name.ilike(q),
                ]
                if is_postgres:
                    search_conditions.extend(
                        [
                            cast(Document.metadata_json["url"].as_string(), String).ilike(q),
                            cast(Document.metadata_json["domain"].as_string(), String).ilike(q),
                        ]
                    )
                else:
                    search_conditions.append(cast(Document.metadata_json, String).ilike(q))
                filtered_docs_stmt = filtered_docs_stmt.where(or_(*search_conditions))

        if tag:
            normalized_tag = tag.strip()
            if normalized_tag:
                if is_postgres:
                    filtered_docs_stmt = filtered_docs_stmt.where(
                        cast(Document.metadata_json, JSONB).contains({"tags": [normalized_tag]})
                    )
                else:
                    filtered_docs_stmt = filtered_docs_stmt.where(
                        cast(Document.metadata_json, String).ilike(f'%"{normalized_tag}"%')
                    )
        return filtered_docs_stmt

    def list_documents(
        self,
        tenant_id: str,
        source_type: str | None = None,
        status: str | None = None,
        *,
        search: str | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[Document, int]], int]:
        page_value = max(1, int(page))
        size_value = max(1, min(int(page_size), 200))
        offset_value = (page_value - 1) * size_value

        filtered_docs_stmt = self._build_documents_filtered_ids_stmt(
            tenant_id,
            source_type=source_type,
            status=status,
            search=search,
            tag=tag,
        )

        total_stmt = select(func.count()).select_from(filtered_docs_stmt.subquery())
        total = int(self.db.scalar(total_stmt) or 0)

        stmt = (
            select(Document, func.count(DocumentChunk.id))
            .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(Document.id.in_(filtered_docs_stmt))
        )
        stmt = (
            stmt.group_by(Document.id)
            .order_by(Document.updated_at.desc(), Document.created_at.desc())
            .offset(offset_value)
            .limit(size_value)
        )
        return list(self.db.execute(stmt).all()), total

    def list_document_tags(
        self,
        tenant_id: str,
        source_type: str | None = None,
        status: str | None = None,
        *,
        search: str | None = None,
        limit: int = 500,
    ) -> list[str]:
        filtered_docs_stmt = self._build_documents_filtered_ids_stmt(
            tenant_id,
            source_type=source_type,
            status=status,
            search=search,
            tag=None,
        )
        if self._is_postgres():
            docs_subquery = filtered_docs_stmt.subquery("filtered_docs")
            tags_json = case(
                (
                    func.jsonb_typeof(cast(Document.metadata_json, JSONB)["tags"]) == "array",
                    cast(Document.metadata_json, JSONB)["tags"],
                ),
                else_=cast(literal("[]"), JSONB),
            )
            tags_values = func.jsonb_array_elements_text(tags_json).table_valued("value").alias("tag_values")
            stmt = (
                select(tags_values.c.value)
                .select_from(Document)
                .join(docs_subquery, docs_subquery.c.id == Document.id)
                .join(tags_values, true())
                .group_by(tags_values.c.value)
                .order_by(func.lower(tags_values.c.value))
                .limit(max(1, min(int(limit), 2000)))
            )
            return [str(value) for value in self.db.scalars(stmt) if str(value or "").strip()]

        rows = self.db.execute(
            select(Document.metadata_json).where(Document.id.in_(filtered_docs_stmt))
        ).all()
        tags: dict[str, str] = {}
        for (metadata,) in rows:
            raw = (metadata or {}).get("tags") if isinstance(metadata, dict) else None
            if not isinstance(raw, list):
                continue
            for item in raw:
                tag = str(item or "").strip()
                if not tag:
                    continue
                lowered = tag.lower()
                if lowered not in tags:
                    tags[lowered] = tag
                if len(tags) >= max(1, min(int(limit), 2000)):
                    return sorted(tags.values(), key=lambda value: value.lower())
        return sorted(tags.values(), key=lambda value: value.lower())

    def enqueue_storage_cleanup_task(
        self,
        *,
        tenant_id: str,
        document_id: str,
        storage_path: str,
        error_message: str | None = None,
        auto_commit: bool = True,
    ) -> StorageCleanupTask:
        now = datetime.now(timezone.utc)
        row = self.db.scalar(
            select(StorageCleanupTask).where(
                StorageCleanupTask.tenant_id == tenant_id,
                StorageCleanupTask.storage_path == storage_path,
            )
        )
        if row is None:
            row = StorageCleanupTask(
                tenant_id=tenant_id,
                document_id=document_id,
                storage_path=storage_path,
                status="pending",
                attempt_count=0,
                last_error=(error_message or "")[:500] or None,
                next_attempt_at=now,
                locked_at=None,
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
        else:
            row.document_id = document_id
            row.status = "pending"
            row.last_error = (error_message or "")[:500] or row.last_error
            row.next_attempt_at = now
            row.locked_at = None
            row.updated_at = now
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def claim_storage_cleanup_tasks(
        self,
        *,
        limit: int = 100,
        running_stale_after_s: int = 300,
    ) -> list[StorageCleanupTask]:
        now = datetime.now(timezone.utc)
        running_cutoff = now - timedelta(seconds=max(1, running_stale_after_s))
        stmt = (
            select(StorageCleanupTask)
            .where(
                or_(
                    and_(
                        StorageCleanupTask.status == "pending",
                        StorageCleanupTask.next_attempt_at <= now,
                    ),
                    and_(
                        StorageCleanupTask.status == "running",
                        or_(
                            StorageCleanupTask.locked_at.is_(None),
                            StorageCleanupTask.locked_at < running_cutoff,
                        ),
                    ),
                )
            )
            .order_by(StorageCleanupTask.next_attempt_at.asc(), StorageCleanupTask.created_at.asc())
            .limit(max(1, min(int(limit), 500)))
            .with_for_update(skip_locked=True)
        )
        rows = list(self.db.scalars(stmt))
        for row in rows:
            row.status = "running"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.locked_at = now
            row.updated_at = now
        self.db.flush()
        return rows

    def complete_storage_cleanup_task(self, row: StorageCleanupTask, auto_commit: bool = True) -> None:
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()

    def reschedule_storage_cleanup_task(
        self,
        row: StorageCleanupTask,
        *,
        error_message: str,
        max_retries: int,
        base_delay_s: int = 30,
        auto_commit: bool = True,
    ) -> bool:
        now = datetime.now(timezone.utc)
        attempts = int(row.attempt_count or 0)
        row.last_error = (error_message or "")[:500] or None
        row.locked_at = None
        row.updated_at = now
        if attempts >= max(1, int(max_retries)):
            row.status = "failed"
            if auto_commit:
                self.db.commit()
            else:
                self.db.flush()
            return False
        delay_s = min(max(1, int(base_delay_s)) * (2 ** max(0, attempts - 1)), 3600)
        row.status = "pending"
        row.next_attempt_at = now + timedelta(seconds=delay_s)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return True

    def purge_failed_storage_cleanup_tasks(
        self,
        *,
        older_than_days: int,
        limit: int = 200,
        auto_commit: bool = True,
    ) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(older_than_days)))
        ids = list(
            self.db.scalars(
                select(StorageCleanupTask.id)
                .where(
                    StorageCleanupTask.status == "failed",
                    StorageCleanupTask.updated_at < cutoff,
                )
                .order_by(StorageCleanupTask.updated_at.asc())
                .limit(max(1, min(int(limit), 2000)))
            )
        )
        if not ids:
            return 0
        self.db.execute(delete(StorageCleanupTask).where(StorageCleanupTask.id.in_(ids)))
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return len(ids)

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

    def search_document_chunks_text(
        self,
        tenant_id: str,
        normalized_query: str,
        source_type: str,
        limit: int = 5,
    ) -> list[dict]:
        raw_tokens = [token.strip().lower() for token in re.findall(r"[a-zA-Z0-9а-яА-ЯёЁ_-]+", normalized_query or "")]
        tokens = [
            token for token in raw_tokens
            if len(token) >= 3 and token not in self._TEXT_FALLBACK_STOPWORDS
        ][:8]
        if not tokens:
            return []
        conditions = [DocumentChunk.content.ilike(f"%{token}%") for token in tokens]
        stmt = (
            select(Document, DocumentChunk)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .where(
                Document.tenant_id == tenant_id,
                Document.source_type == source_type,
                Document.status == "approved",
                Document.enabled_in_retrieval.is_(True),
                or_(*conditions),
            )
            .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc())
            .limit(limit)
        )
        rows = self.db.execute(stmt).all()
        return [
            {
                "id": str(chunk.id),
                "document_id": str(document.id),
                "web_snapshot_id": str(document.id) if document.source_type == "website_snapshot" else "",
                "title": document.title,
                "content": chunk.content,
                "page": (chunk.metadata_json or {}).get("page"),
                "section": (chunk.metadata_json or {}).get("section"),
                "domain": (document.metadata_json or {}).get("domain"),
                "url": (document.metadata_json or {}).get("url"),
            }
            for document, chunk in rows
        ]

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

    def get_document_ingestion_job_by_id(self, job_id: str) -> DocumentIngestionJob | None:
        stmt = select(DocumentIngestionJob).where(DocumentIngestionJob.id == job_id)
        return self.db.scalar(stmt)

    def claim_document_ingestion_job(
        self,
        job_id: str,
        *,
        running_stale_after_s: int = 300,
    ) -> DocumentIngestionJob | None:
        now = datetime.now(timezone.utc)
        running_cutoff = now - timedelta(seconds=max(1, running_stale_after_s))
        stmt = (
            update(DocumentIngestionJob)
            .where(
                DocumentIngestionJob.id == job_id,
                or_(
                    DocumentIngestionJob.status == "pending",
                    and_(
                        DocumentIngestionJob.status == "running",
                        or_(
                            DocumentIngestionJob.started_at.is_(None),
                            DocumentIngestionJob.started_at < running_cutoff,
                        ),
                    ),
                ),
            )
            .values(
                status="running",
                attempt_count=DocumentIngestionJob.attempt_count + 1,
                started_at=now,
                updated_at=now,
                finished_at=None,
                error_message=None,
            )
            .returning(DocumentIngestionJob.id)
        )
        claimed_job_id = self.db.scalar(stmt)
        if claimed_job_id is None:
            self.db.rollback()
            return None
        self.db.commit()
        return self.get_document_ingestion_job_by_id(str(claimed_job_id))

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

    def list_recoverable_document_ingestion_jobs(
        self,
        *,
        limit: int = 50,
        running_stale_after_s: int = 300,
    ) -> list[DocumentIngestionJob]:
        running_cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, running_stale_after_s))
        stmt = (
            select(DocumentIngestionJob)
            .where(
                or_(
                    DocumentIngestionJob.status == "pending",
                    and_(
                        DocumentIngestionJob.status == "running",
                        or_(
                            DocumentIngestionJob.started_at.is_(None),
                            DocumentIngestionJob.started_at < running_cutoff,
                        ),
                    ),
                )
            )
            .order_by(DocumentIngestionJob.created_at.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def list_documents_retrieval_flags(self, tenant_id: str, document_ids: list[str]) -> dict[str, dict]:
        if not document_ids:
            return {}
        stmt = select(
            Document.id,
            Document.status,
            Document.enabled_in_retrieval,
            Document.source_type,
        ).where(
            Document.tenant_id == tenant_id,
            Document.id.in_(document_ids),
        )
        rows = self.db.execute(stmt).all()
        return {
            str(row.id): {
                "status": str(row.status),
                "enabled_in_retrieval": bool(row.enabled_in_retrieval),
                "source_type": str(row.source_type),
            }
            for row in rows
        }

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
