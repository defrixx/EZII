from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import Integer, String, and_, asc, case, cast, delete, desc, func, literal, or_, select, true, update
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
    User,
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
        exclude_document_ids: set[str] | None = None,
    ):
        filtered_docs_stmt = select(Document.id).where(Document.tenant_id == tenant_id)
        if source_type:
            filtered_docs_stmt = filtered_docs_stmt.where(Document.source_type == source_type)
        if status:
            filtered_docs_stmt = filtered_docs_stmt.where(Document.status == status)
        if exclude_document_ids:
            normalized_ids = [item for item in {str(item).strip() for item in exclude_document_ids} if item]
            if normalized_ids:
                filtered_docs_stmt = filtered_docs_stmt.where(Document.id.notin_(normalized_ids))

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
        unused_only: bool = False,
        unused_window_days: int = 30,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[Document, int]], int]:
        page_value = max(1, int(page))
        size_value = max(1, min(int(page_size), 200))
        offset_value = (page_value - 1) * size_value

        exclude_document_ids: set[str] = set()
        if bool(unused_only):
            analytics = self.source_impact_analytics(
                tenant_id,
                window_days=unused_window_days,
                limit=1,
            )
            used_ids = {
                str(item.get("source_id") or "").strip()
                for item in analytics.get("metrics", [])
                if int(item.get("usage_count") or 0) > 0
            }
            exclude_document_ids = {item for item in used_ids if item}

        filtered_docs_stmt = self._build_documents_filtered_ids_stmt(
            tenant_id,
            source_type=source_type,
            status=status,
            search=search,
            tag=tag,
            exclude_document_ids=exclude_document_ids,
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

    def get_document_ingestion_job_by_id(self, tenant_id: str, job_id: str) -> DocumentIngestionJob | None:
        stmt = select(DocumentIngestionJob).where(
            DocumentIngestionJob.id == job_id,
            DocumentIngestionJob.tenant_id == tenant_id,
        )
        return self.db.scalar(stmt)

    def claim_document_ingestion_job(
        self,
        tenant_id: str,
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
                DocumentIngestionJob.tenant_id == tenant_id,
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
        return self.get_document_ingestion_job_by_id(tenant_id, str(claimed_job_id))

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

    def _token_usage_int_expr(self, field: str):
        if not self._is_postgres():
            return literal(0)
        token_usage = cast(ResponseTrace.token_usage, JSONB)
        return func.coalesce(cast(token_usage["provider_usage"][field].astext, String), "0")

    def _rewrite_usage_int_expr(self):
        if not self._is_postgres():
            return literal(0)
        token_usage = cast(ResponseTrace.token_usage, JSONB)
        return func.coalesce(cast(token_usage["rewrite_usage"]["total_tokens"].astext, String), "0")

    def user_token_usage_analytics(
        self,
        tenant_id: str,
        *,
        window_days: int = 30,
        page: int = 1,
        page_size: int = 10,
        sort_order: str = "desc",
        only_with_requests: bool = False,
    ) -> dict:
        days = max(1, min(int(window_days), 365))
        page_value = max(1, int(page))
        size_value = max(1, min(int(page_size), 200))
        offset_value = (page_value - 1) * size_value
        normalized_sort = "asc" if str(sort_order).lower() == "asc" else "desc"
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)

        total_users = int(
            self.db.scalar(
                select(func.count()).select_from(
                    select(User.id).where(User.tenant_id == tenant_id).subquery()
                )
            )
            or 0
        )

        if not self._is_postgres():
            users = self.db.execute(
                select(User.id, User.email, User.role).where(User.tenant_id == tenant_id)
            ).all()

            def _to_int(value) -> int:
                try:
                    return int(value or 0)
                except Exception:
                    return 0

            aggregates: dict[str, dict] = {
                str(user.id): {
                    "user_id": str(user.id),
                    "email": str(user.email),
                    "role": str(user.role),
                    "request_count": 0,
                    "provider_prompt_tokens": 0,
                    "provider_completion_tokens": 0,
                    "provider_total_tokens": 0,
                    "rewrite_total_tokens": 0,
                    "total_tokens": 0,
                    "avg_tokens_per_request": 0.0,
                    "last_request_at": None,
                }
                for user in users
            }
            traces = self.db.execute(
                select(ResponseTrace.user_id, ResponseTrace.created_at, ResponseTrace.token_usage).where(
                    ResponseTrace.tenant_id == tenant_id,
                    ResponseTrace.created_at >= cutoff,
                )
            ).all()
            for trace in traces:
                user_id = str(trace.user_id)
                if user_id not in aggregates:
                    continue
                token_usage = trace.token_usage or {}
                provider_usage = token_usage.get("provider_usage") if isinstance(token_usage, dict) else {}
                rewrite_usage = token_usage.get("rewrite_usage") if isinstance(token_usage, dict) else {}
                agg = aggregates[user_id]
                agg["request_count"] += 1
                agg["provider_prompt_tokens"] += _to_int((provider_usage or {}).get("prompt_tokens"))
                agg["provider_completion_tokens"] += _to_int((provider_usage or {}).get("completion_tokens"))
                agg["provider_total_tokens"] += _to_int((provider_usage or {}).get("total_tokens"))
                agg["rewrite_total_tokens"] += _to_int((rewrite_usage or {}).get("total_tokens"))
                agg["total_tokens"] = agg["provider_total_tokens"] + agg["rewrite_total_tokens"]
                if not agg["last_request_at"] or trace.created_at > agg["last_request_at"]:
                    agg["last_request_at"] = trace.created_at

            for agg in aggregates.values():
                request_count = int(agg["request_count"])
                agg["avg_tokens_per_request"] = round(agg["total_tokens"] / request_count, 2) if request_count > 0 else 0.0

            all_items = list(aggregates.values())
            if only_with_requests:
                all_items = [item for item in all_items if int(item["request_count"] or 0) > 0]
            filtered_total = len(all_items)

            sorted_items = sorted(
                all_items,
                key=lambda item: (
                    int(item["total_tokens"]) if normalized_sort == "asc" else -int(item["total_tokens"]),
                    str(item["email"]).lower(),
                ),
            )
            paged_items = sorted_items[offset_value : offset_value + size_value]

            window_start = cutoff
            window_end = now
            month_traces = self.db.execute(
                select(ResponseTrace.user_id, ResponseTrace.token_usage).where(
                    ResponseTrace.tenant_id == tenant_id,
                    ResponseTrace.created_at >= window_start,
                    ResponseTrace.created_at < window_end,
                )
            ).all()
            month_prompt_tokens = 0
            month_completion_tokens = 0
            month_provider_total = 0
            month_rewrite_total = 0
            active_users: set[str] = set()
            for trace in month_traces:
                token_usage = trace.token_usage or {}
                provider_usage = token_usage.get("provider_usage") if isinstance(token_usage, dict) else {}
                rewrite_usage = token_usage.get("rewrite_usage") if isinstance(token_usage, dict) else {}
                month_prompt_tokens += _to_int((provider_usage or {}).get("prompt_tokens"))
                month_completion_tokens += _to_int((provider_usage or {}).get("completion_tokens"))
                month_provider_total += _to_int((provider_usage or {}).get("total_tokens"))
                month_rewrite_total += _to_int((rewrite_usage or {}).get("total_tokens"))
                active_users.add(str(trace.user_id))

            month_request_count = len(month_traces)
            month_total_tokens = month_provider_total + month_rewrite_total
            active_users_in_month = len(active_users)
            avg_tokens_per_request = (
                round(month_total_tokens / month_request_count, 2) if month_request_count > 0 else 0.0
            )
            avg_tokens_per_active_user = (
                round(month_total_tokens / active_users_in_month, 2) if active_users_in_month > 0 else 0.0
            )
            elapsed_days = days
            avg_daily_tokens = round(month_total_tokens / elapsed_days, 2)
            projected_month_total_tokens = round(avg_daily_tokens * elapsed_days, 2)

            return {
                "window_days": days,
                "sort_order": normalized_sort,
                "page": page_value,
                "page_size": size_value,
                "total": filtered_total,
                "items": paged_items,
                "summary": {
                    "month_start": window_start,
                    "month_end": window_end,
                    "month_total_tokens": month_total_tokens,
                    "month_prompt_tokens": month_prompt_tokens,
                    "month_completion_tokens": month_completion_tokens,
                    "month_rewrite_tokens": month_rewrite_total,
                    "month_request_count": month_request_count,
                    "active_users_in_month": active_users_in_month,
                    "total_users": total_users,
                    "avg_tokens_per_request": avg_tokens_per_request,
                    "avg_tokens_per_active_user": avg_tokens_per_active_user,
                    "avg_daily_tokens": avg_daily_tokens,
                    "projected_month_total_tokens": projected_month_total_tokens,
                },
            }

        prompt_expr = cast(self._token_usage_int_expr("prompt_tokens"), Integer)
        completion_expr = cast(self._token_usage_int_expr("completion_tokens"), Integer)
        provider_total_expr = cast(self._token_usage_int_expr("total_tokens"), Integer)
        rewrite_total_expr = cast(self._rewrite_usage_int_expr(), Integer)

        traces_agg = (
            select(
                ResponseTrace.user_id.label("user_id"),
                func.count(ResponseTrace.id).label("request_count"),
                func.coalesce(func.sum(prompt_expr), 0).label("provider_prompt_tokens"),
                func.coalesce(func.sum(completion_expr), 0).label("provider_completion_tokens"),
                func.coalesce(func.sum(provider_total_expr), 0).label("provider_total_tokens"),
                func.coalesce(func.sum(rewrite_total_expr), 0).label("rewrite_total_tokens"),
                func.max(ResponseTrace.created_at).label("last_request_at"),
            )
            .where(
                ResponseTrace.tenant_id == tenant_id,
                ResponseTrace.created_at >= cutoff,
            )
            .group_by(ResponseTrace.user_id)
            .subquery("traces_agg")
        )

        total_tokens_expr = (
            func.coalesce(traces_agg.c.provider_total_tokens, 0)
            + func.coalesce(traces_agg.c.rewrite_total_tokens, 0)
        )
        order_expr = asc(total_tokens_expr) if normalized_sort == "asc" else desc(total_tokens_expr)
        request_count_expr = func.coalesce(traces_agg.c.request_count, 0)
        row_filters = [User.tenant_id == tenant_id]
        if only_with_requests:
            row_filters.append(request_count_expr > 0)

        filtered_total = int(
            self.db.scalar(
                select(func.count())
                .select_from(User)
                .outerjoin(traces_agg, traces_agg.c.user_id == User.id)
                .where(and_(*row_filters))
            )
            or 0
        )

        rows = self.db.execute(
            select(
                User.id,
                User.email,
                User.role,
                request_count_expr.label("request_count"),
                func.coalesce(traces_agg.c.provider_prompt_tokens, 0).label("provider_prompt_tokens"),
                func.coalesce(traces_agg.c.provider_completion_tokens, 0).label("provider_completion_tokens"),
                func.coalesce(traces_agg.c.provider_total_tokens, 0).label("provider_total_tokens"),
                func.coalesce(traces_agg.c.rewrite_total_tokens, 0).label("rewrite_total_tokens"),
                total_tokens_expr.label("total_tokens"),
                traces_agg.c.last_request_at.label("last_request_at"),
            )
            .select_from(User)
            .outerjoin(traces_agg, traces_agg.c.user_id == User.id)
            .where(and_(*row_filters))
            .order_by(order_expr, User.email.asc())
            .offset(offset_value)
            .limit(size_value)
        ).all()

        window_start = cutoff
        window_end = now
        month_agg = self.db.execute(
            select(
                func.coalesce(func.sum(prompt_expr), 0).label("month_prompt_tokens"),
                func.coalesce(func.sum(completion_expr), 0).label("month_completion_tokens"),
                func.coalesce(func.sum(provider_total_expr), 0).label("month_provider_total_tokens"),
                func.coalesce(func.sum(rewrite_total_expr), 0).label("month_rewrite_tokens"),
                func.count(ResponseTrace.id).label("month_request_count"),
                func.count(func.distinct(ResponseTrace.user_id)).label("active_users_in_month"),
            ).where(
                ResponseTrace.tenant_id == tenant_id,
                ResponseTrace.created_at >= window_start,
                ResponseTrace.created_at < window_end,
            )
        ).one()

        month_provider_total = int(month_agg.month_provider_total_tokens or 0)
        month_rewrite_total = int(month_agg.month_rewrite_tokens or 0)
        month_total_tokens = month_provider_total + month_rewrite_total
        month_request_count = int(month_agg.month_request_count or 0)
        active_users_in_month = int(month_agg.active_users_in_month or 0)
        avg_tokens_per_request = (
            round(month_total_tokens / month_request_count, 2) if month_request_count > 0 else 0.0
        )
        avg_tokens_per_active_user = (
            round(month_total_tokens / active_users_in_month, 2) if active_users_in_month > 0 else 0.0
        )
        elapsed_days = days
        avg_daily_tokens = round(month_total_tokens / elapsed_days, 2)
        projected_month_total_tokens = round(avg_daily_tokens * elapsed_days, 2)

        items: list[dict] = []
        for row in rows:
            request_count = int(row.request_count or 0)
            provider_total = int(row.provider_total_tokens or 0)
            rewrite_total = int(row.rewrite_total_tokens or 0)
            total_tokens = int(row.total_tokens or 0)
            items.append(
                {
                    "user_id": str(row.id),
                    "email": str(row.email),
                    "role": str(row.role),
                    "request_count": request_count,
                    "provider_prompt_tokens": int(row.provider_prompt_tokens or 0),
                    "provider_completion_tokens": int(row.provider_completion_tokens or 0),
                    "provider_total_tokens": provider_total,
                    "rewrite_total_tokens": rewrite_total,
                    "total_tokens": total_tokens,
                    "avg_tokens_per_request": round(total_tokens / request_count, 2) if request_count > 0 else 0.0,
                    "last_request_at": row.last_request_at,
                }
            )

        return {
            "window_days": days,
            "sort_order": normalized_sort,
            "page": page_value,
            "page_size": size_value,
            "total": filtered_total,
            "items": items,
            "summary": {
                "month_start": window_start,
                "month_end": window_end,
                "month_total_tokens": month_total_tokens,
                "month_prompt_tokens": int(month_agg.month_prompt_tokens or 0),
                "month_completion_tokens": int(month_agg.month_completion_tokens or 0),
                "month_rewrite_tokens": month_rewrite_total,
                "month_request_count": month_request_count,
                "active_users_in_month": active_users_in_month,
                "total_users": total_users,
                "avg_tokens_per_request": avg_tokens_per_request,
                "avg_tokens_per_active_user": avg_tokens_per_active_user,
                "avg_daily_tokens": avg_daily_tokens,
                "projected_month_total_tokens": projected_month_total_tokens,
            },
        }

    def source_impact_analytics(
        self,
        tenant_id: str,
        *,
        window_days: int = 30,
        limit: int = 10,
    ) -> dict:
        days = max(1, min(int(window_days), 365))
        top_limit = max(1, min(int(limit), 2000))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        documents = list(
            self.db.scalars(
                select(Document)
                .where(Document.tenant_id == tenant_id)
                .order_by(Document.updated_at.desc(), Document.created_at.desc())
            )
        )
        if not documents:
            return {
                "window_days": days,
                "total_sources": 0,
                "used_sources": 0,
                "unused_sources": 0,
                "top_used": [],
                "never_used": [],
                "metrics": [],
            }

        traces = list(
            self.db.scalars(
                select(ResponseTrace).where(
                    ResponseTrace.tenant_id == tenant_id,
                    ResponseTrace.created_at >= cutoff,
                )
            )
        )
        usage_count_by_source: dict[str, int] = {}
        last_used_at_by_source: dict[str, datetime] = {}
        for trace in traces:
            seen_in_trace: set[str] = set()
            for source_id in [*(trace.document_ids or []), *(trace.web_snapshot_ids or [])]:
                normalized = str(source_id or "").strip()
                if not normalized or normalized in seen_in_trace:
                    continue
                seen_in_trace.add(normalized)
                usage_count_by_source[normalized] = usage_count_by_source.get(normalized, 0) + 1
                if (
                    normalized not in last_used_at_by_source
                    or trace.created_at > last_used_at_by_source[normalized]
                ):
                    last_used_at_by_source[normalized] = trace.created_at

        used_items: list[dict] = []
        never_used_items: list[dict] = []
        metrics: list[dict] = []

        for document in documents:
            source_id = str(document.id)
            usage_count = int(usage_count_by_source.get(source_id, 0))
            last_used_at = last_used_at_by_source.get(source_id)
            item = {
                "id": source_id,
                "title": document.title,
                "source_type": document.source_type,
                "status": document.status,
                "enabled_in_retrieval": bool(document.enabled_in_retrieval),
                "usage_count": usage_count,
                "last_used_at": last_used_at,
                "updated_at": document.updated_at,
            }
            metrics.append(
                {
                    "source_id": source_id,
                    "usage_count": usage_count,
                    "last_used_at": last_used_at,
                }
            )
            if usage_count > 0:
                used_items.append(item)
            else:
                never_used_items.append(item)

        used_items.sort(
            key=lambda item: (
                int(item["usage_count"]),
                item["last_used_at"] or datetime.min.replace(tzinfo=timezone.utc),
                item["updated_at"],
            ),
            reverse=True,
        )
        never_used_items.sort(
            key=lambda item: item["updated_at"],
            reverse=True,
        )
        metrics.sort(
            key=lambda item: (
                int(item["usage_count"]),
                item["last_used_at"] or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        return {
            "window_days": days,
            "total_sources": len(documents),
            "used_sources": len(used_items),
            "unused_sources": len(never_used_items),
            "top_used": used_items[:top_limit],
            "never_used": never_used_items[:top_limit],
            "metrics": metrics,
        }
