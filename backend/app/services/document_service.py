import asyncio
import hashlib
import logging
import mimetypes
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session
from urllib.parse import urljoin, urlparse
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
        if (parsed.scheme or "").lower() != "https":
            raise HTTPException(status_code=400, detail="Website snapshot URL must use https")
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

    @staticmethod
    def _resolve_public_ips_sync(host: str) -> set[str]:
        lowered = (host or "").strip().lower()
        if not lowered:
            raise RuntimeError("Snapshot host is empty")
        try:
            infos = socket.getaddrinfo(lowered, 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise RuntimeError("Website snapshot host must resolve publicly") from exc
        resolved: set[str] = set()
        for info in infos:
            raw_ip = info[4][0]
            ip = ipaddress.ip_address(raw_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise RuntimeError("Website snapshot host must resolve publicly")
            resolved.add(raw_ip)
        if not resolved:
            raise RuntimeError("Website snapshot host must resolve publicly")
        return resolved

    @staticmethod
    def _response_peer_ip(response: httpx.Response) -> str | None:
        extensions = getattr(response, "extensions", {}) or {}
        stream = extensions.get("network_stream")
        if stream is None:
            return None
        getter = getattr(stream, "get_extra_info", None)
        if not callable(getter):
            return None
        server_addr = getter("server_addr")
        if isinstance(server_addr, tuple) and server_addr:
            return str(server_addr[0])
        return None

    def _assert_peer_ip(self, response: httpx.Response, allowed_ips: set[str], *, context: str) -> None:
        peer_ip = self._response_peer_ip(response)
        if peer_ip is None:
            raise RuntimeError(
                f"Peer IP verification is unavailable for {context}: transport does not expose network metadata"
            )
        if peer_ip not in allowed_ips:
            raise RuntimeError("Website snapshot resolved host mismatch")

    @staticmethod
    async def _read_response_bytes_with_limit(response: httpx.Response, max_bytes: int) -> bytes:
        data = bytearray()
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                max_mb = max(1, int(max_bytes / (1024 * 1024)))
                raise RuntimeError(f"Website snapshot response exceeds {max_mb} MB")
            data.extend(chunk)
        return bytes(data)

    @classmethod
    async def _assert_public_snapshot_host_async(cls, url: str) -> str:
        return await asyncio.to_thread(cls._assert_public_snapshot_host, url)

    @staticmethod
    async def _read_upload_bytes_with_limit(file: UploadFile, max_bytes: int) -> bytes:
        chunk_size = 1024 * 1024
        total = 0
        data = bytearray()
        while True:
            used_fallback_read = False
            try:
                chunk = await file.read(chunk_size)
            except TypeError:
                # Backward-compatible for simple test doubles implementing read() without a size argument.
                chunk = await file.read()
                used_fallback_read = True
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                max_mb = int(max_bytes / (1024 * 1024))
                raise HTTPException(
                    status_code=413,
                    detail=f"File size exceeds the allowed limit of {max_mb} MB. Upload a smaller file.",
                )
            data.extend(chunk)
            if used_fallback_read:
                break
        return bytes(data)

    def storage_root(self) -> Path:
        return Path(self.settings.document_storage_dir)

    @staticmethod
    def _cleanup_storage_file(storage_path: Path | None) -> None:
        if storage_path is None:
            return
        try:
            if storage_path.exists():
                storage_path.unlink(missing_ok=True)
            for parent in [storage_path.parent, storage_path.parent.parent]:
                if parent.exists():
                    try:
                        parent.rmdir()
                    except OSError:
                        pass
        except Exception as exc:
            logger.warning(
                "Failed to cleanup document storage path=%s: %s",
                str(storage_path),
                str(exc)[:300],
            )

    @staticmethod
    def _delete_storage_file_strict(storage_path: Path | None) -> None:
        if storage_path is None:
            return
        if storage_path.exists():
            storage_path.unlink()
        for parent in [storage_path.parent, storage_path.parent.parent]:
            if parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    pass

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        normalized = text.replace("\xa0", " ").replace("\u200b", "")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    @staticmethod
    def _looks_binary_bytes(file_bytes: bytes) -> bool:
        if not file_bytes:
            return False
        sample = file_bytes[:4096]
        if b"\x00" in sample:
            return True
        control = sum(1 for b in sample if b < 32 and b not in (9, 10, 13, 12, 8))
        return (control / max(1, len(sample))) > 0.10

    @classmethod
    def _decode_text_payload(cls, file_bytes: bytes, *, error_detail: str) -> str:
        if cls._looks_binary_bytes(file_bytes):
            raise HTTPException(status_code=400, detail="Binary content is not allowed for text uploads")
        for encoding in ("utf-8", "utf-8-sig", "cp1251"):
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise HTTPException(status_code=400, detail=error_detail)

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
        raw = cls._decode_text_payload(file_bytes, error_detail="Failed to decode Markdown document")
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
        decoded = cls._decode_text_payload(file_bytes, error_detail="Failed to decode text document")

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
        max_bytes = int(self.settings.document_upload_max_bytes)
        file_bytes = await self._read_upload_bytes_with_limit(file, max_bytes)
        if not file_bytes:
            raise HTTPException(status_code=400, detail="File is empty")
        effective_mime = file.content_type or mimetypes.guess_type(file.filename or "")[0]
        suffix = Path(file.filename or "").suffix.lower()
        if (effective_mime or "").lower() in {"text/plain", "text/markdown", "text/x-markdown"} or suffix in {".txt", ".md"}:
            if b"\x00" in file_bytes[:4096]:
                raise HTTPException(status_code=400, detail="Binary content is not allowed for text uploads")
        # Validate supported type and parseability before writing to disk.
        blocks = self.extract_blocks(file_bytes, effective_mime, file.filename)
        if not blocks:
            raise HTTPException(status_code=400, detail="Document does not contain extractable text blocks")

        storage_path: Path | None = None
        try:
            document = self.repo.create_document(
                {
                    "tenant_id": tenant_id,
                    "title": payload.title or Path(file.filename or "document").stem or "document",
                    "source_type": "upload",
                    "mime_type": effective_mime,
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
        except Exception:
            self.db.rollback()
            self._cleanup_storage_file(storage_path)
            raise

    async def create_website_snapshot(
        self,
        tenant_id: str,
        user_id: str,
        url: str,
        title: str | None,
        enabled_in_retrieval: bool,
        tags: list[str] | None = None,
    ) -> tuple[Document, str]:
        domain = await self._assert_public_snapshot_host_async(url)
        snapshot_title = title or domain or "Website Snapshot"
        storage_path: Path | None = None
        try:
            document = self.repo.create_document(
                {
                    "tenant_id": tenant_id,
                    "title": snapshot_title,
                    "source_type": "website_snapshot",
                    "mime_type": "text/plain",
                    "file_name": "snapshot.txt",
                    "storage_path": "",
                    "status": "processing",
                    "enabled_in_retrieval": enabled_in_retrieval,
                    "checksum": None,
                    "created_by": user_id,
                    "metadata_json": {"url": url, "domain": domain, "tags": list(tags or [])},
                },
                auto_commit=False,
            )
            storage_path = self.storage_root() / tenant_id / str(document.id) / "snapshot.txt"
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
        except Exception:
            self.db.rollback()
            self._cleanup_storage_file(storage_path)
            raise

    def queue_reindex(self, document: Document, triggered_by: str) -> str:
        if document.status == "processing":
            raise HTTPException(status_code=409, detail="Document is already being processed")
        previous_status = str(document.status or "").strip()
        previous_approved_by = document.approved_by
        previous_approved_at = document.approved_at.isoformat() if document.approved_at else None
        self.repo.update_document(document, {"status": "processing"}, auto_commit=False)
        job = self.repo.create_document_ingestion_job(
            {
                "tenant_id": str(document.tenant_id),
                "document_id": str(document.id),
                "status": "pending",
                "triggered_by": triggered_by,
                "metadata_json": {
                    "reason": "reindex",
                    "previous_status": previous_status,
                    "previous_approved_by": previous_approved_by,
                    "previous_approved_at": previous_approved_at,
                },
            },
            auto_commit=False,
        )
        self.db.commit()
        self.db.refresh(document)
        return str(job.id)

    def _publish_chunks(self, document: Document, chunks: list[DocumentChunk], embeddings: list[list[float]]) -> None:
        if document.enabled_in_retrieval and document.status == "approved" and len(embeddings) != len(chunks):
            raise RuntimeError("Document publish requires one embedding per chunk")
        tenant_id = str(document.tenant_id)
        document_id = str(document.id)
        if not document.enabled_in_retrieval or document.status != "approved":
            self.vector.delete_by_field("document_id", document_id, tenant_id=tenant_id)
            return
        publish_token = str(uuid.uuid4())
        entries: list[dict[str, Any]] = []
        for row, vector in zip(chunks, embeddings):
            page = row.metadata_json.get("page") if isinstance(row.metadata_json, dict) else None
            section = row.metadata_json.get("section") if isinstance(row.metadata_json, dict) else None
            payload_source_type = "website_snapshot" if document.source_type == "website_snapshot" else "upload"
            web_snapshot_id = document_id if payload_source_type == "website_snapshot" else None
            entries.append(
                {
                    "id": str(row.id),
                    "vector": vector,
                    "payload": {
                        "tenant_id": tenant_id,
                        "document_id": document_id,
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
                        "publish_token": publish_token,
                    },
                }
            )
        self.vector.upsert_entries(entries)
        # Remove stale versions only after the new version is fully upserted.
        self.vector.delete_by_filters(
            tenant_id=tenant_id,
            must={"document_id": document_id},
            must_not={"publish_token": publish_token},
        )

    def process_job(self, job_id: str) -> None:
        job = self.repo.claim_document_ingestion_job(job_id, running_stale_after_s=300)
        if job is None:
            return
        document = self.repo.get_document(str(job.tenant_id), str(job.document_id))
        if document is None:
            self.repo.update_document_ingestion_job(job, {"status": "failed", "error_message": "Document not found"})
            return

        try:
            storage_path = Path(document.storage_path or "")
            if document.source_type == "website_snapshot":
                raw = asyncio.run(self._fetch_snapshot_bytes(document))
                storage_path.write_bytes(raw)
                document.checksum = hashlib.sha256(raw).hexdigest()
                document.mime_type = "text/plain"
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
            metadata = job.metadata_json or {}
            reason = str(metadata.get("reason") or "").strip()
            previous_status = str(metadata.get("previous_status") or "").strip().lower()
            preserve_approval = (
                (reason == "reindex" and previous_status == "approved")
                or (reason == "enable_retrieval" and document.status == "approved")
            )
            preserved_approved_by = metadata.get("previous_approved_by") if reason == "reindex" else document.approved_by
            preserved_approved_at = document.approved_at
            if reason == "reindex":
                previous_approved_at = str(metadata.get("previous_approved_at") or "").strip()
                if previous_approved_at:
                    try:
                        preserved_approved_at = datetime.fromisoformat(previous_approved_at)
                    except ValueError:
                        preserved_approved_at = None
            self.repo.update_document(
                document,
                {
                    "status": "approved" if preserve_approval else "draft",
                    "approved_by": str(preserved_approved_by) if preserve_approval and preserved_approved_by else None,
                    "approved_at": preserved_approved_at if preserve_approval else None,
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
        embeddings: list[list[float]] = []
        if document.enabled_in_retrieval:
            try:
                provider = self.retrieval._provider_for_tenant(str(document.tenant_id))
                embeddings = asyncio.run(provider.embeddings([chunk.content for chunk in chunks]))
            except Exception as exc:
                logger.warning(
                    "Document publish embeddings failed tenant=%s document_id=%s: %s",
                    str(document.tenant_id),
                    str(document.id),
                    str(exc)[:300],
                )
                raise HTTPException(status_code=502, detail="Failed to generate embeddings for document approval") from exc
            if len(embeddings) != len(chunks):
                raise HTTPException(status_code=502, detail="Embedding provider returned inconsistent chunk count")

        approved = self.repo.update_document(
            document,
            {
                "status": "approved",
                "approved_by": approved_by,
                "approved_at": self._utcnow(),
            },
            auto_commit=False,
        )
        try:
            self._publish_chunks(approved, chunks, embeddings)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise HTTPException(status_code=502, detail="Failed to publish approved document to retrieval index") from exc
        self.db.refresh(approved)
        return approved

    def archive_document(self, document: Document) -> Document:
        document = self.repo.update_document(
            document,
            {"status": "archived", "enabled_in_retrieval": False},
            auto_commit=False,
        )
        try:
            self.vector.delete_by_field("document_id", str(document.id), tenant_id=str(document.tenant_id))
        except Exception as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=502,
                detail="Failed to remove archived document vectors",
            ) from exc
        try:
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise HTTPException(status_code=502, detail="Failed to archive document") from exc
        self.db.refresh(document)
        return document

    def set_enabled_in_retrieval(self, document: Document, enabled: bool) -> Document:
        updated = self.repo.update_document(document, {"enabled_in_retrieval": enabled}, auto_commit=False)
        if not enabled:
            try:
                self.vector.delete_by_field("document_id", str(document.id), tenant_id=str(document.tenant_id))
            except Exception as exc:
                self.db.rollback()
                raise HTTPException(
                    status_code=502,
                    detail="Failed to remove document vectors for retrieval disablement",
                ) from exc
            try:
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                raise HTTPException(status_code=502, detail="Failed to update retrieval flag") from exc
            self.db.refresh(updated)
            return updated
        if updated.status == "approved":
            chunks = self.repo.list_document_chunks(str(updated.tenant_id), str(updated.id))
            if not chunks:
                raise HTTPException(status_code=400, detail="Document cannot be enabled without indexed chunks")
            try:
                provider = self.retrieval._provider_for_tenant(str(updated.tenant_id))
                embeddings = asyncio.run(provider.embeddings([chunk.content for chunk in chunks]))
            except Exception as exc:
                raise HTTPException(status_code=502, detail="Failed to generate embeddings for retrieval enablement") from exc
            if len(embeddings) != len(chunks):
                raise HTTPException(status_code=502, detail="Embedding provider returned inconsistent chunk count")
            self._publish_chunks(updated, chunks, embeddings)
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
        storage_path_raw = str(document.storage_path or "").strip()
        storage_path = Path(storage_path_raw) if storage_path_raw else None
        quarantine_path: Path | None = None
        moved_to_quarantine = False
        if storage_path is not None and storage_path.exists():
            quarantine_path = storage_path.with_name(
                f".deleting-{storage_path.name}.{uuid.uuid4().hex}.tmp"
            )
            storage_path.replace(quarantine_path)
            moved_to_quarantine = True
        try:
            self.vector.delete_by_field("document_id", str(document.id), tenant_id=str(document.tenant_id))
        except Exception as exc:
            if moved_to_quarantine and quarantine_path is not None and quarantine_path.exists():
                assert storage_path is not None
                storage_path.parent.mkdir(parents=True, exist_ok=True)
                quarantine_path.replace(storage_path)
            raise HTTPException(status_code=502, detail="Failed to delete document vectors") from exc
        try:
            self.repo.delete_document(document, auto_commit=False)
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            if moved_to_quarantine and quarantine_path is not None and quarantine_path.exists():
                assert storage_path is not None
                storage_path.parent.mkdir(parents=True, exist_ok=True)
                quarantine_path.replace(storage_path)
            raise HTTPException(status_code=502, detail="Failed to delete document assets") from exc
        try:
            self._delete_storage_file_strict(quarantine_path if moved_to_quarantine else storage_path)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Failed to delete document storage file") from exc

    @classmethod
    def run_ingestion_job(cls, job_id: str) -> None:
        with SessionLocal() as db:
            cls(db).process_job(job_id)

    @classmethod
    def recover_pending_jobs(
        cls,
        *,
        limit: int = 50,
        running_stale_after_s: int = 300,
    ) -> int:
        with SessionLocal() as db:
            repo = AdminRepository(db)
            jobs = repo.list_recoverable_document_ingestion_jobs(
                limit=limit,
                running_stale_after_s=running_stale_after_s,
            )
            if not jobs:
                return 0
            service = cls(db)
            processed = 0
            for job in jobs:
                try:
                    service.process_job(str(job.id))
                    processed += 1
                except Exception:
                    logger.exception("Failed recovering ingestion job job_id=%s", str(job.id))
            return processed

    async def _fetch_snapshot_bytes(self, document: Document) -> bytes:
        url = str((document.metadata_json or {}).get("url") or "").strip()
        if not url:
            raise RuntimeError("Website snapshot URL is missing")

        settings = getattr(self, "settings", None) or get_settings()

        async def _assert_host_public(candidate_url: str) -> str:
            custom_assert = getattr(self, "_assert_public_snapshot_host", None)
            if callable(custom_assert):
                return await asyncio.to_thread(custom_assert, candidate_url)
            return await self._assert_public_snapshot_host_async(candidate_url)

        requested_host = await _assert_host_public(url)
        max_snapshot_bytes = max(1, int(settings.website_snapshot_max_bytes))

        current_url = url
        response_bytes: bytes | None = None
        final_url: str | None = None
        max_redirects = 5
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for _ in range(max_redirects + 1):
                current_host = await _assert_host_public(current_url)
                allowed_ips = await asyncio.to_thread(self._resolve_public_ips_sync, current_host)
                stream_request = getattr(client, "stream", None)
                if callable(stream_request):
                    async with stream_request("GET", current_url) as resp:
                        self._assert_peer_ip(resp, allowed_ips, context="website_snapshot")

                        if resp.status_code in {301, 302, 303, 307, 308}:
                            location = (resp.headers.get("location") or "").strip()
                            if not location:
                                raise RuntimeError("Website snapshot redirect location is missing")
                            next_url = urljoin(current_url, location)
                            next_host = await _assert_host_public(next_url)
                            if not self._is_allowed_redirect_domain(requested_host, next_host):
                                raise RuntimeError("Website snapshot redirects are allowed only within the same domain")
                            current_url = next_url
                            continue

                        resp.raise_for_status()
                        response_bytes = await self._read_response_bytes_with_limit(resp, max_snapshot_bytes)
                        final_url = str(resp.url)
                        break

                resp = await client.get(current_url)
                self._assert_peer_ip(resp, allowed_ips, context="website_snapshot")
                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = (resp.headers.get("location") or "").strip()
                    if not location:
                        raise RuntimeError("Website snapshot redirect location is missing")
                    next_url = urljoin(current_url, location)
                    next_host = await _assert_host_public(next_url)
                    if not self._is_allowed_redirect_domain(requested_host, next_host):
                        raise RuntimeError("Website snapshot redirects are allowed only within the same domain")
                    current_url = next_url
                    continue

                resp.raise_for_status()
                raw_content = getattr(resp, "content", None)
                if raw_content is None:
                    raw_content = str(getattr(resp, "text", "")).encode("utf-8")
                if len(raw_content) > max_snapshot_bytes:
                    max_mb = max(1, int(max_snapshot_bytes / (1024 * 1024)))
                    raise RuntimeError(f"Website snapshot response exceeds {max_mb} MB")
                response_bytes = bytes(raw_content)
                final_url = str(getattr(resp, "url", current_url))
                break
            else:
                raise RuntimeError("Website snapshot redirect limit exceeded")

        if response_bytes is None or final_url is None:
            raise RuntimeError("Website snapshot fetch failed")

        final_host = await _assert_host_public(final_url)
        if not self._is_allowed_redirect_domain(requested_host, final_host):
            raise RuntimeError("Website snapshot redirects are allowed only within the same domain")
        soup = BeautifulSoup(response_bytes.decode("utf-8", errors="replace"), "html.parser")
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
            {**(document.metadata_json or {}), "domain": domain, "url": final_url}
        )
        return cleaned.encode("utf-8")

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _is_allowed_redirect_domain(requested: str, final_domain: str) -> bool:
        req = requested.strip().lower()
        final = final_domain.strip().lower()
        return final == req or final.endswith(f".{req}")
