import asyncio
import hashlib
import logging
import mimetypes
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import ipaddress

from app.core.config import get_settings
from app.core.logging_utils import redact_pii, safe_payload
from app.db.session import SessionLocal
from app.models import Document, DocumentChunk
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import validate_document_metadata_json
from app.services.retrieval_service import RetrievalService
from app.services.vector_service import VectorService

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

logger = logging.getLogger(__name__)


@dataclass
class ParsedBlock:
    text: str
    page: int | None
    section: str | None


class DocumentService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.repo = AdminRepository(db)
        self.retrieval = RetrievalService(db)
        self.vector = VectorService(self.settings.qdrant_url, self.settings.qdrant_documents_collection)

    @staticmethod
    def _assert_public_snapshot_host(url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise HTTPException(status_code=400, detail="Website snapshot URL must include a host")
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise HTTPException(status_code=400, detail="Website snapshot host must resolve publicly") from exc
        for info in infos:
            raw_ip = info[4][0]
            ip = ipaddress.ip_address(raw_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise HTTPException(status_code=400, detail="Website snapshot host must resolve publicly")
        return host

    def storage_root(self) -> Path:
        return Path(self.settings.document_storage_dir)

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        normalized = text.replace("\xa0", " ").replace("\u200b", "")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    @classmethod
    def _markdown_to_text(cls, text: str) -> str:
        cleaned = text
        cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"(?m)^\s{0,3}>\s?", "", cleaned)
        cleaned = re.sub(r"(?m)^\s*[-*+]\s+", "", cleaned)
        cleaned = re.sub(r"(?m)^\s*\d+\.\s+", "", cleaned)
        cleaned = re.sub(r"[*_~#]+", "", cleaned)
        return cls._normalize_whitespace(cleaned)

    @classmethod
    def _split_paragraphs(cls, text: str) -> list[str]:
        return [block.strip() for block in re.split(r"\n\s*\n", cls._normalize_whitespace(text)) if block.strip()]

    @classmethod
    def _extract_pdf_blocks(cls, file_bytes: bytes) -> list[ParsedBlock]:
        if PdfReader is None:
            raise HTTPException(status_code=500, detail="PDF ingestion dependency is not installed")
        reader = PdfReader(BytesIO(file_bytes))
        blocks: list[ParsedBlock] = []
        for index, page in enumerate(reader.pages, start=1):
            page_text = cls._normalize_whitespace(page.extract_text() or "")
            if not page_text:
                continue
            current_section: str | None = None
            for paragraph in cls._split_paragraphs(page_text):
                if len(paragraph) <= 120 and paragraph == paragraph.upper():
                    current_section = paragraph
                blocks.append(ParsedBlock(text=paragraph, page=index, section=current_section))
        return blocks

    @classmethod
    def _extract_markdown_blocks(cls, file_bytes: bytes) -> list[ParsedBlock]:
        raw = ""
        for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                raw = file_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if not raw:
            raise HTTPException(status_code=400, detail="Failed to decode Markdown document")
        lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        blocks: list[ParsedBlock] = []
        current_section: str | None = None
        paragraph: list[str] = []

        def flush_paragraph() -> None:
            if not paragraph:
                return
            text = cls._markdown_to_text("\n".join(paragraph))
            paragraph.clear()
            if text:
                blocks.append(ParsedBlock(text=text, page=None, section=current_section))

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                flush_paragraph()
                heading = cls._markdown_to_text(stripped.lstrip("#").strip())
                current_section = heading or current_section
                if heading:
                    blocks.append(ParsedBlock(text=heading, page=None, section=current_section))
                continue
            if not stripped:
                flush_paragraph()
                continue
            paragraph.append(line)
        flush_paragraph()
        return [block for block in blocks if block.text]

    @classmethod
    def _extract_text_blocks(cls, file_bytes: bytes) -> list[ParsedBlock]:
        decoded = ""
        for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                decoded = file_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if not decoded:
            raise HTTPException(status_code=400, detail="Failed to decode text document")

        blocks: list[ParsedBlock] = []
        current_section: str | None = None
        for paragraph in cls._split_paragraphs(decoded):
            if len(paragraph) <= 120 and paragraph == paragraph.upper():
                current_section = paragraph
            blocks.append(ParsedBlock(text=paragraph, page=None, section=current_section))
        return blocks

    @classmethod
    def extract_blocks(cls, file_bytes: bytes, mime_type: str | None, file_name: str | None) -> list[ParsedBlock]:
        effective_mime = (mime_type or "").lower()
        suffix = Path(file_name or "").suffix.lower()
        if effective_mime == "application/pdf" or suffix == ".pdf":
            return cls._extract_pdf_blocks(file_bytes)
        if effective_mime in {"text/markdown", "text/x-markdown"} or suffix == ".md":
            return cls._extract_markdown_blocks(file_bytes)
        if effective_mime == "text/plain" or suffix == ".txt":
            return cls._extract_text_blocks(file_bytes)
        raise HTTPException(status_code=400, detail="Only PDF, MD, and TXT documents are supported")

    def chunk_blocks(self, blocks: list[ParsedBlock]) -> list[dict[str, Any]]:
        if not blocks:
            return []

        max_chars = self.settings.document_chunk_size_chars
        overlap_chars = self.settings.document_chunk_overlap_chars
        chunks: list[dict[str, Any]] = []
        current_blocks: list[ParsedBlock] = []
        current_length = 0

        def flush_chunk() -> None:
            nonlocal current_blocks, current_length
            if not current_blocks:
                return
            content = "\n\n".join(block.text for block in current_blocks).strip()
            if not content:
                current_blocks = []
                current_length = 0
                return
            pages = [block.page for block in current_blocks if block.page is not None]
            sections = [block.section for block in current_blocks if block.section]
            chunks.append(
                {
                    "content": content,
                    "page": pages[0] if pages else None,
                    "section": sections[0] if sections else None,
                    "metadata_json": {
                        "page": pages[0] if pages else None,
                        "pages": pages,
                        "section": sections[0] if sections else None,
                        "sections": sections,
                    },
                }
            )

            overlap: list[ParsedBlock] = []
            overlap_len = 0
            for block in reversed(current_blocks):
                block_len = len(block.text)
                if overlap_len >= overlap_chars and overlap:
                    break
                overlap.insert(0, block)
                overlap_len += block_len
            current_blocks = overlap
            current_length = sum(len(block.text) for block in current_blocks)

        for block in blocks:
            text = self._normalize_whitespace(block.text)
            if not text:
                continue
            candidate_len = current_length + len(text) + (2 if current_blocks else 0)
            if current_blocks and candidate_len > max_chars:
                flush_chunk()
            current_blocks.append(ParsedBlock(text=text, page=block.page, section=block.section))
            current_length += len(text) + (2 if current_blocks else 0)
        flush_chunk()

        return [
            {
                "chunk_index": index,
                "content": chunk["content"],
                "token_count": len(re.findall(r"\w+", chunk["content"])),
                "embedding_model": None,
                "metadata_json": chunk["metadata_json"],
            }
            for index, chunk in enumerate(chunks)
            if chunk["content"]
        ]

    async def create_upload(self, tenant_id: str, user_id: str, file: UploadFile, payload: Any) -> tuple[Document, str]:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="File is empty")
        if len(file_bytes) > int(self.settings.document_upload_max_bytes):
            max_mb = int(self.settings.document_upload_max_bytes / (1024 * 1024))
            raise HTTPException(
                status_code=413,
                detail=f"File size exceeds the allowed limit of {max_mb} MB. Upload a smaller file.",
            )

        document = self.repo.create_document(
            {
                "tenant_id": tenant_id,
                "title": payload.title or Path(file.filename or "document").stem or "document",
                "source_type": "upload",
                "mime_type": file.content_type or mimetypes.guess_type(file.filename or "")[0],
                "file_name": file.filename,
                "storage_path": "",
                "status": "processing",
                "enabled_in_retrieval": payload.enabled_in_retrieval,
                "checksum": hashlib.sha256(file_bytes).hexdigest(),
                "created_by": user_id,
                "metadata_json": validate_document_metadata_json(payload.metadata_json),
            },
            auto_commit=False,
        )

        safe_name = Path(file.filename or "document.bin").name
        storage_path = self.storage_root() / tenant_id / str(document.id) / safe_name
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(file_bytes)
        self.repo.update_document(
            document,
            {"storage_path": str(storage_path), "mime_type": document.mime_type or "application/octet-stream"},
            auto_commit=False,
        )
        job = self.repo.create_document_ingestion_job(
            {
                "tenant_id": tenant_id,
                "document_id": str(document.id),
                "status": "pending",
                "triggered_by": user_id,
                "metadata_json": {"reason": "upload"},
            },
            auto_commit=False,
        )
        self.db.commit()
        self.db.refresh(document)
        return document, str(job.id)

    async def create_website_snapshot(
        self,
        tenant_id: str,
        user_id: str,
        url: str,
        title: str | None,
        enabled_in_retrieval: bool,
        tags: list[str] | None = None,
    ) -> tuple[Document, str]:
        domain = self._assert_public_snapshot_host(url)
        snapshot_title = title or domain or "Website Snapshot"
        document = self.repo.create_document(
            {
                "tenant_id": tenant_id,
                "title": snapshot_title,
                "source_type": "website_snapshot",
                "mime_type": "text/html",
                "file_name": "snapshot.html",
                "storage_path": "",
                "status": "processing",
                "enabled_in_retrieval": enabled_in_retrieval,
                "checksum": None,
                "created_by": user_id,
                "metadata_json": {"url": url, "domain": domain, "tags": list(tags or [])},
            },
            auto_commit=False,
        )
        storage_path = self.storage_root() / tenant_id / str(document.id) / "snapshot.html"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_text("", encoding="utf-8")
        self.repo.update_document(document, {"storage_path": str(storage_path)}, auto_commit=False)
        job = self.repo.create_document_ingestion_job(
            {
                "tenant_id": tenant_id,
                "document_id": str(document.id),
                "status": "pending",
                "triggered_by": user_id,
                "metadata_json": {"reason": "website_snapshot"},
            },
            auto_commit=False,
        )
        self.db.commit()
        self.db.refresh(document)
        return document, str(job.id)

    def queue_reindex(self, document: Document, triggered_by: str) -> str:
        if document.status == "processing":
            raise HTTPException(status_code=409, detail="Document is already being processed")
        self.repo.update_document(document, {"status": "processing"}, auto_commit=False)
        job = self.repo.create_document_ingestion_job(
            {
                "tenant_id": str(document.tenant_id),
                "document_id": str(document.id),
                "status": "pending",
                "triggered_by": triggered_by,
                "metadata_json": {"reason": "reindex"},
            },
            auto_commit=False,
        )
        self.db.commit()
        self.db.refresh(document)
        return str(job.id)

    def _publish_chunks(self, document: Document, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> None:
        self.vector.delete_by_field("document_id", str(document.id))
        if not document.enabled_in_retrieval or document.status != "approved":
            return
        if len(embeddings) != len(chunks):
            return
        for row, vector in zip(chunks, embeddings):
            page = row.metadata_json.get("page") if isinstance(row.metadata_json, dict) else None
            section = row.metadata_json.get("section") if isinstance(row.metadata_json, dict) else None
            payload_source_type = "website_snapshot" if document.source_type == "website_snapshot" else "document"
            web_snapshot_id = str(document.id) if payload_source_type == "website_snapshot" else None
            self.vector.upsert_entry(
                str(row.id),
                str(document.tenant_id),
                vector,
                {
                    "tenant_id": str(document.tenant_id),
                    "document_id": str(document.id),
                    "chunk_id": str(row.id),
                    "source_type": payload_source_type,
                    "title": document.title,
                    "status": document.status,
                    "page": page,
                    "section": section,
                    "enabled_in_retrieval": document.enabled_in_retrieval,
                    "content": row.content,
                    "web_snapshot_id": web_snapshot_id,
                    "url": (document.metadata_json or {}).get("url"),
                    "domain": (document.metadata_json or {}).get("domain"),
                },
            )

    def process_job(self, job_id: str) -> None:
        job = self.repo.get_document_ingestion_job_by_id(job_id)
        if job is None:
            return
        document = self.repo.get_document(str(job.tenant_id), str(job.document_id))
        if document is None:
            self.repo.update_document_ingestion_job(job, {"status": "failed", "error_message": "Document not found"})
            return

        self.repo.update_document_ingestion_job(
            job,
            {
                "status": "running",
                "attempt_count": int(job.attempt_count or 0) + 1,
                "started_at": self._utcnow(),
            },
            auto_commit=False,
        )
        self.db.commit()

        try:
            storage_path = Path(document.storage_path or "")
            if document.source_type == "website_snapshot":
                raw = asyncio.run(self._fetch_snapshot_bytes(document))
                storage_path.write_bytes(raw)
                document.checksum = hashlib.sha256(raw).hexdigest()
                document.mime_type = "text/html"
                self.db.flush()
            elif not storage_path.exists():
                raise FileNotFoundError("Document file is missing from storage")
            else:
                raw = storage_path.read_bytes()

            blocks = self.extract_blocks(raw, document.mime_type, document.file_name)
            if not blocks:
                raise RuntimeError("Document does not contain extractable text blocks")
            chunks_payload = self.chunk_blocks(blocks)
            if not chunks_payload:
                raise RuntimeError("Document chunking produced no content")
            provider = self.retrieval._provider_for_tenant(str(document.tenant_id))
            embeddings: list[list[float]] = []
            if chunks_payload:
                try:
                    embeddings = asyncio.run(provider.embeddings([chunk["content"] for chunk in chunks_payload]))
                except Exception as exc:
                    logger.warning(
                        "Document embedding generation degraded tenant=%s document_id=%s job_id=%s: %s",
                        str(document.tenant_id),
                        str(document.id),
                        job_id,
                        str(exc)[:300],
                    )
                    embeddings = []
                if embeddings and len(embeddings) != len(chunks_payload):
                    logger.warning(
                        "Document embedding generation returned inconsistent chunk count tenant=%s document_id=%s requested=%s received=%s",
                        str(document.tenant_id),
                        str(document.id),
                        len(chunks_payload),
                        len(embeddings),
                    )
                    embeddings = []

            for chunk in chunks_payload:
                chunk["embedding_model"] = provider.embedding_model if embeddings else None
            chunk_rows = self.repo.replace_document_chunks(
                str(document.tenant_id),
                str(document.id),
                chunks_payload,
                auto_commit=False,
            )
            self.repo.update_document(
                document,
                {
                    "status": "draft",
                    "approved_by": None,
                    "approved_at": None,
                },
                auto_commit=False,
            )
            self.db.flush()
            self._publish_chunks(document, chunk_rows, embeddings)
            self.repo.update_document_ingestion_job(
                job,
                {"status": "completed", "error_message": None, "finished_at": self._utcnow()},
                auto_commit=False,
            )
            self.db.commit()
            audit_user_id = str(job.triggered_by or document.created_by or "").strip()
            if audit_user_id:
                self.repo.add_audit_log(
                    str(document.tenant_id),
                    audit_user_id,
                    "ingestion_completed",
                    "document",
                    str(document.id),
                    {"chunk_count": len(chunk_rows)},
                )
        except Exception as exc:
            logger.exception(
                "Document ingestion failed tenant=%s document_id=%s job_id=%s file=%s source_type=%s",
                str(document.tenant_id) if document is not None else "",
                str(document.id) if document is not None else "",
                job_id,
                document.file_name if document is not None else "",
                document.source_type if document is not None else "",
            )
            self.db.rollback()
            job = self.repo.get_document_ingestion_job_by_id(job_id)
            document = self.repo.get_document(str(job.tenant_id), str(job.document_id)) if job is not None else None
            if job is not None:
                self.repo.update_document_ingestion_job(
                    job,
                    {
                        "status": "failed",
                        "error_message": redact_pii(str(exc))[:2000],
                        "finished_at": self._utcnow(),
                    },
                    auto_commit=False,
                )
            if document is not None:
                self.repo.update_document(document, {"status": "failed"}, auto_commit=False)
            self.db.commit()
            if document is not None:
                self.repo.add_error_log(
                    tenant_id=str(document.tenant_id),
                    user_id=str(job.triggered_by or document.created_by) if job is not None else None,
                    chat_id=None,
                    error_type="document_ingestion_error",
                    message=redact_pii(str(exc))[:2000],
                    metadata=safe_payload(
                        {
                            "document_id": str(document.id),
                            "job_id": job_id,
                            "file_name": document.file_name or "",
                        }
                    ),
                )

    def approve_document(self, document: Document, approved_by: str) -> Document:
        chunks = self.repo.list_document_chunks(str(document.tenant_id), str(document.id))
        if not chunks:
            raise HTTPException(status_code=400, detail="Document cannot be approved without indexed chunks")
        if document.status == "archived":
            raise HTTPException(status_code=400, detail="Archived documents must be reindexed before approval")
        approved = self.repo.update_document(
            document,
            {
                "status": "approved",
                "approved_by": approved_by,
                "approved_at": self._utcnow(),
                "enabled_in_retrieval": True,
            },
            auto_commit=False,
        )
        embeddings: list[list[float]] = []
        try:
            provider = self.retrieval._provider_for_tenant(str(approved.tenant_id))
            embeddings = asyncio.run(provider.embeddings([chunk.content for chunk in chunks]))
        except Exception as exc:
            logger.warning(
                "Document publish embeddings degraded tenant=%s document_id=%s: %s",
                str(approved.tenant_id),
                str(approved.id),
                str(exc)[:300],
            )
            embeddings = []
        self._publish_chunks(approved, chunks, embeddings)
        self.db.commit()
        self.db.refresh(approved)
        return approved

    def archive_document(self, document: Document) -> Document:
        document = self.repo.update_document(
            document,
            {"status": "archived", "enabled_in_retrieval": False},
            auto_commit=False,
        )
        self.vector.delete_by_field("document_id", str(document.id))
        self.db.commit()
        self.db.refresh(document)
        return document

    def set_enabled_in_retrieval(self, document: Document, enabled: bool) -> Document:
        updated = self.repo.update_document(document, {"enabled_in_retrieval": enabled}, auto_commit=False)
        if not enabled:
            self.vector.delete_by_field("document_id", str(document.id))
            self.db.commit()
            self.db.refresh(updated)
            return updated
        if updated.status == "approved":
            job = self.repo.create_document_ingestion_job(
                {
                    "tenant_id": str(updated.tenant_id),
                    "document_id": str(updated.id),
                    "status": "pending",
                    "triggered_by": updated.approved_by or updated.created_by,
                    "metadata_json": {"reason": "enable_retrieval"},
                },
                auto_commit=False,
            )
            self.db.commit()
            self.db.refresh(updated)
            return updated
        self.db.commit()
        self.db.refresh(updated)
        return updated

    def update_document_metadata(self, document: Document, metadata_json: dict[str, Any]) -> Document:
        merged = dict(document.metadata_json or {})
        merged.update(metadata_json)
        return self.repo.update_document(document, {"metadata_json": validate_document_metadata_json(merged)})

    def delete_document(self, document: Document) -> None:
        self.vector.delete_by_field("document_id", str(document.id))
        storage_path = Path(document.storage_path or "")
        self.repo.delete_document(document, auto_commit=False)
        self.db.commit()
        if storage_path.exists():
            storage_path.unlink(missing_ok=True)
            for parent in [storage_path.parent, storage_path.parent.parent]:
                if parent.exists():
                    try:
                        parent.rmdir()
                    except OSError:
                        pass

    @classmethod
    def run_ingestion_job(cls, job_id: str) -> None:
        with SessionLocal() as db:
            cls(db).process_job(job_id)

    async def _fetch_snapshot_bytes(self, document: Document) -> bytes:
        url = str((document.metadata_json or {}).get("url") or "").strip()
        if not url:
            raise RuntimeError("Website snapshot URL is missing")
        self._assert_public_snapshot_host(url)
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        final_host = self._assert_public_snapshot_host(str(resp.url))
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        cleaned = self._normalize_whitespace(text)
        if not cleaned:
            raise RuntimeError("Website snapshot contains no extractable text")
        domain = str((document.metadata_json or {}).get("domain") or final_host or "")
        title = soup.title.string.strip() if soup.title and soup.title.string else document.title
        document.title = title or document.title
        document.file_name = "snapshot.txt"
        document.mime_type = "text/plain"
        document.metadata_json = validate_document_metadata_json(
            {**(document.metadata_json or {}), "domain": domain, "url": str(resp.url)}
        )
        return cleaned.encode("utf-8")

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)
