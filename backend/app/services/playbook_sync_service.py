import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Document
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import PlaybookDeleteOut, PlaybookSyncOut, validate_document_metadata_json
from app.services.document_service import DocumentService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaybookFile:
    path: str
    content: bytes
    checksum: str


class PlaybookSyncService:
    REPO_OWNER = "defrixx"
    REPO_NAME = "Product-security-playbook"
    BRANCH = "main"
    MAX_FILES = 200
    MAX_TOTAL_BYTES = 100 * 1024 * 1024
    TIMEOUT_S = 20
    FILE_NAME_SUFFIX = ".en.md"
    SKIPPED_PATH_PARTS = {".git", ".github", "node_modules", "vendor", "__pycache__"}

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.repo = AdminRepository(db)
        self.documents = DocumentService(db)

    @property
    def repository_name(self) -> str:
        return f"{self.REPO_OWNER}/{self.REPO_NAME}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "EZII-playbook-sync",
        }
        return headers

    @classmethod
    def _is_allowed_path(cls, path: str) -> bool:
        try:
            pure = PurePosixPath(path)
        except ValueError:
            return False
        if pure.is_absolute() or ".." in pure.parts:
            return False
        if any(part.startswith(".") or part in cls.SKIPPED_PATH_PARTS for part in pure.parts):
            return False
        return pure.name.lower().endswith(cls.FILE_NAME_SUFFIX)

    async def _fetch_commit_sha(self, client: httpx.AsyncClient) -> str:
        owner = self.REPO_OWNER
        repo = self.REPO_NAME
        branch = self.BRANCH
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{quote(branch, safe='')}"
        response = await client.get(url, headers=self._headers())
        if response.status_code == 404:
            raise HTTPException(status_code=502, detail="Configured playbook repository or branch was not found")
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Failed to resolve playbook repository commit")
        sha = str((response.json() or {}).get("sha") or "").strip()
        if not sha:
            raise HTTPException(status_code=502, detail="GitHub commit response did not include a SHA")
        return sha

    async def _fetch_repository_files(self) -> tuple[str, list[PlaybookFile]]:
        owner = self.REPO_OWNER
        repo = self.REPO_NAME
        max_files = self.MAX_FILES
        max_total_bytes = self.MAX_TOTAL_BYTES
        max_file_bytes = max(1, int(self.settings.document_upload_max_bytes))
        timeout = httpx.Timeout(float(self.TIMEOUT_S))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            commit_sha = await self._fetch_commit_sha(client)
            tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1"
            tree_response = await client.get(tree_url, headers=self._headers())
            if tree_response.status_code >= 400:
                raise HTTPException(status_code=502, detail="Failed to list playbook repository files")
            tree = (tree_response.json() or {}).get("tree") or []
            paths = [
                str(item.get("path") or "")
                for item in tree
                if item.get("type") == "blob" and self._is_allowed_path(str(item.get("path") or ""))
            ]
            paths = sorted(paths)
            if len(paths) > max_files:
                raise HTTPException(status_code=413, detail=f"Playbook sync exceeds the configured limit of {max_files} files")

            files: list[PlaybookFile] = []
            total_bytes = 0
            for path in paths:
                encoded_path = quote(path, safe="/")
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{commit_sha}/{encoded_path}"
                response = await client.get(raw_url, headers={"User-Agent": "EZII-playbook-sync"})
                if response.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"Failed to download playbook file: {path}")
                content = response.content
                if len(content) > max_file_bytes:
                    max_mb = max(1, int(max_file_bytes / (1024 * 1024)))
                    raise HTTPException(status_code=413, detail=f"Playbook file exceeds the configured limit of {max_mb} MB: {path}")
                total_bytes += len(content)
                if total_bytes > max_total_bytes:
                    max_mb = max(1, int(max_total_bytes / (1024 * 1024)))
                    raise HTTPException(status_code=413, detail=f"Playbook sync exceeds the configured limit of {max_mb} MB")
                files.append(PlaybookFile(path=path, content=content, checksum=hashlib.sha256(content).hexdigest()))
            return commit_sha, files

    def _metadata_for_file(self, file: PlaybookFile, commit_sha: str) -> dict[str, Any]:
        return validate_document_metadata_json(
            {
                "tags": ["product-security-playbook", "security-playbook"],
                "playbook": {
                    "repo": self.repository_name,
                    "branch": self.BRANCH,
                    "commit_sha": commit_sha,
                    "path": file.path,
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        )

    def _storage_path_for(self, tenant_id: str, document_id: str, source_path: str) -> Path:
        safe_name = PurePosixPath(source_path).name or "playbook.md"
        return self.documents.storage_root() / tenant_id / document_id / safe_name

    def _title_for_path(self, path: str) -> str:
        stem = PurePosixPath(path).stem.replace("_", " ").replace("-", " ").strip()
        return self.documents._normalize_document_title(stem.title() if stem else path, "Product Security Playbook")

    def _validate_file(self, file: PlaybookFile, mime_type: str) -> None:
        blocks = self.documents.extract_blocks(file.content, mime_type, file.path)
        if not blocks:
            raise HTTPException(status_code=400, detail=f"Playbook file does not contain extractable text: {file.path}")

    def _create_document(self, *, tenant_id: str, user_id: str, file: PlaybookFile, commit_sha: str) -> tuple[Document, str]:
        mime_type = mimetypes.guess_type(file.path)[0] or "text/markdown"
        self._validate_file(file, mime_type)
        document = self.repo.create_document(
            {
                "tenant_id": tenant_id,
                "title": self._title_for_path(file.path),
                "source_type": "github_playbook",
                "mime_type": mime_type,
                "file_name": PurePosixPath(file.path).name,
                "storage_path": "",
                "status": "processing",
                "enabled_in_retrieval": True,
                "checksum": file.checksum,
                "created_by": user_id,
                "metadata_json": self._metadata_for_file(file, commit_sha),
            },
            auto_commit=False,
        )
        storage_path = self._storage_path_for(tenant_id, str(document.id), file.path)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(file.content)
        self.repo.update_document(document, {"storage_path": str(storage_path)}, auto_commit=False)
        job = self.repo.create_document_ingestion_job(
            {
                "tenant_id": tenant_id,
                "document_id": str(document.id),
                "status": "pending",
                "triggered_by": user_id,
                "metadata_json": {"reason": "playbook_sync", "repo": self.repository_name, "path": file.path},
            },
            auto_commit=False,
        )
        return document, str(job.id)

    def _update_document(self, *, document: Document, user_id: str, file: PlaybookFile, commit_sha: str) -> str:
        mime_type = mimetypes.guess_type(file.path)[0] or "text/markdown"
        self._validate_file(file, mime_type)
        storage_path = self._storage_path_for(str(document.tenant_id), str(document.id), file.path)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(file.content)
        previous_status = str(document.status or "").strip()
        previous_approved_by = document.approved_by
        previous_approved_at = document.approved_at.isoformat() if document.approved_at else None
        self.repo.update_document(
            document,
            {
                "title": self._title_for_path(file.path),
                "mime_type": mime_type,
                "file_name": PurePosixPath(file.path).name,
                "storage_path": str(storage_path),
                "checksum": file.checksum,
                "status": "processing",
                "metadata_json": self._metadata_for_file(file, commit_sha),
            },
            auto_commit=False,
        )
        job = self.repo.create_document_ingestion_job(
            {
                "tenant_id": str(document.tenant_id),
                "document_id": str(document.id),
                "status": "pending",
                "triggered_by": user_id,
                "metadata_json": {
                    "reason": "reindex",
                    "source": "playbook_sync",
                    "repo": self.repository_name,
                    "path": file.path,
                    "previous_status": previous_status,
                    "previous_approved_by": previous_approved_by,
                    "previous_approved_at": previous_approved_at,
                },
            },
            auto_commit=False,
        )
        return str(job.id)

    async def sync(self, tenant_id: str, user_id: str) -> PlaybookSyncOut:
        commit_sha, files = await self._fetch_repository_files()
        existing = self.repo.list_playbook_documents(tenant_id, self.repository_name)
        existing_by_path = {
            str((row.metadata_json or {}).get("playbook", {}).get("path") or ""): row
            for row in existing
            if isinstance(row.metadata_json, dict)
        }
        seen_paths = {file.path for file in files}
        result = PlaybookSyncOut(
            repository=self.repository_name,
            branch=self.BRANCH,
            commit_sha=commit_sha,
            total_files=len(files),
        )
        try:
            for file in files:
                row = existing_by_path.get(file.path)
                if row is not None and str(row.checksum or "") == file.checksum:
                    result.skipped += 1
                    continue
                if row is None:
                    document, job_id = self._create_document(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        file=file,
                        commit_sha=commit_sha,
                    )
                    result.created += 1
                    result.queued_document_ids.append(str(document.id))
                    result.queued_job_ids.append(job_id)
                else:
                    job_id = self._update_document(document=row, user_id=user_id, file=file, commit_sha=commit_sha)
                    result.updated += 1
                    result.queued_document_ids.append(str(row.id))
                    result.queued_job_ids.append(job_id)

            for path, row in existing_by_path.items():
                if path in seen_paths or row.status == "archived":
                    continue
                self.repo.update_document(row, {"status": "archived", "enabled_in_retrieval": False}, auto_commit=False)
                result.archived += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Playbook sync failed tenant=%s repo=%s", tenant_id, self.repository_name)
            raise
        return result

    def delete_all_sources(self, tenant_id: str) -> PlaybookDeleteOut:
        rows = self.repo.list_playbook_documents(tenant_id, self.repository_name)
        document_service = DocumentService(self.db)
        deleted = 0
        for row in rows:
            document_service.delete_document(row)
            deleted += 1
        return PlaybookDeleteOut(repository=self.repository_name, deleted=deleted)
