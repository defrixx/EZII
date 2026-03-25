from datetime import datetime, timezone
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.api.deps import db_dep
from app.core.config import get_settings
from app.core.security import AuthContext, require_admin
from app.repositories.admin_repository import AdminRepository
from app.services.document_service import DocumentService
from app.services.provider_service import OpenRouterProvider
from app.schemas.admin import (
    DocumentChunkOut,
    DocumentDetailOut,
    DocumentOut,
    DocumentUploadForm,
    DocumentUpdateIn,
    LogOut,
    PendingRegistrationOut,
    ProviderSettingsIn,
    ProviderSettingsOut,
    TraceOut,
    WebsiteSnapshotCreate,
)

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


async def _verify_embedding_dimension(
    *,
    base_url: str,
    api_key: str,
    embedding_model: str,
    timeout_s: int,
) -> None:
    provider = OpenRouterProvider(
        base_url=base_url,
        api_key=api_key,
        model="unused",
        embedding_model=embedding_model,
        timeout_s=timeout_s,
        max_retries=0,
    )
    vectors = await provider.embeddings(["dimension_check"])
    if not vectors or not isinstance(vectors[0], list):
        raise HTTPException(status_code=400, detail="Embedding provider returned empty vector")
    if len(vectors[0]) != settings.embedding_vector_size:
        raise HTTPException(
            status_code=400,
            detail=(
                "Embedding dimension does not match the Qdrant collection: "
                f"expected {settings.embedding_vector_size}, received {len(vectors[0])}"
            ),
        )


def _extract_user_tenant_id(user: dict[str, Any]) -> str:
    attrs = user.get("attributes") or {}
    raw = attrs.get("tenant_id")
    if isinstance(raw, list):
        return str(raw[0]) if raw else ""
    if isinstance(raw, str):
        return raw
    return ""


def _created_at_from_ms(value: Any) -> datetime | None:
    try:
        ms = int(value)
    except Exception:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _validate_provider_base_url_public_sync(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme.lower() != "https":
        raise HTTPException(status_code=400, detail="base_url must use https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise HTTPException(status_code=400, detail="base_url host must be public")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="base_url host must resolve publicly") from exc
    for info in infos:
        raw_ip = info[4][0]
        ip = ipaddress.ip_address(raw_ip)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(status_code=400, detail="base_url host must resolve publicly")


def _to_document_schema(row, chunk_count: int = 0, latest_job: Any | None = None) -> DocumentOut:
    return DocumentOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        title=row.title,
        source_type=row.source_type,
        mime_type=row.mime_type,
        file_name=row.file_name,
        storage_path=None,
        status=row.status,
        enabled_in_retrieval=row.enabled_in_retrieval,
        checksum=row.checksum,
        created_by=row.created_by,
        approved_by=row.approved_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        approved_at=row.approved_at,
        metadata_json=row.metadata_json or {},
        chunk_count=chunk_count,
        ingestion_error=(latest_job.error_message if latest_job and latest_job.error_message else None),
        ingestion_error_at=(latest_job.finished_at if latest_job else None),
    )


def _to_document_chunk_schema(row) -> DocumentChunkOut:
    return DocumentChunkOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        document_id=str(row.document_id),
        chunk_index=row.chunk_index,
        content=row.content,
        token_count=row.token_count,
        embedding_model=row.embedding_model,
        metadata_json=row.metadata_json or {},
        created_at=row.created_at,
    )


def _latest_document_job(repo: Any, tenant_id: str, document_id: str) -> Any | None:
    getter = getattr(repo, "get_latest_document_ingestion_job", None)
    if not callable(getter):
        return None
    return getter(tenant_id, document_id)


def _schedule_document_ingestion(background_tasks: BackgroundTasks, job_id: str) -> None:
    background_tasks.add_task(DocumentService.run_ingestion_job, job_id)


async def _keycloak_admin_token() -> str:
    if not settings.keycloak_admin or not settings.keycloak_admin_password:
        raise HTTPException(status_code=500, detail="KEYCLOAK_ADMIN/KEYCLOAK_ADMIN_PASSWORD are not configured")
    token_url = f"{settings.keycloak_server_url}/realms/{settings.keycloak_admin_realm}/protocol/openid-connect/token"
    form = {
        "grant_type": "password",
        "client_id": settings.keycloak_admin_client_id,
        "username": settings.keycloak_admin,
        "password": settings.keycloak_admin_password,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_url, data=form)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Failed to obtain Keycloak admin token")
    token = resp.json().get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="Keycloak admin token is empty")
    return str(token)


@router.get("/provider", response_model=ProviderSettingsOut)
def get_provider(ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    row = repo.get_provider(ctx.tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider settings are not configured")
    return ProviderSettingsOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        base_url=row.base_url,
        api_key=_mask_secret(AdminRepository.provider_api_key_plain(row)),
        model_name=row.model_name,
        embedding_model=row.embedding_model,
        timeout_s=row.timeout_s,
        retry_policy=row.retry_policy,
        knowledge_mode=row.knowledge_mode,
        empty_retrieval_mode=row.empty_retrieval_mode,
        strict_glossary_mode=row.strict_glossary_mode,
        show_confidence=row.show_confidence,
        show_source_tags=row.show_source_tags,
        response_tone=row.response_tone,
        max_user_messages_total=row.max_user_messages_total,
        chat_context_enabled=row.chat_context_enabled,
        history_user_turn_limit=row.history_user_turn_limit,
        history_message_limit=row.history_message_limit,
        history_token_budget=row.history_token_budget,
        rewrite_history_message_limit=row.rewrite_history_message_limit,
        updated_at=row.updated_at,
    )


@router.put("/provider", response_model=ProviderSettingsOut)
async def put_provider(payload: ProviderSettingsIn, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    existing = repo.get_provider(ctx.tenant_id)
    data = payload.model_dump(exclude_none=True)
    if "base_url" in data:
        data["base_url"] = str(data["base_url"])
        await run_in_threadpool(_validate_provider_base_url_public_sync, str(data["base_url"]))
    incoming_key = data.get("api_key")
    masked_existing = _mask_secret(AdminRepository.provider_api_key_plain(existing)) if existing else ""
    if existing and (
        incoming_key is None
        or str(incoming_key).strip() == ""
        or str(incoming_key) == masked_existing
    ):
        data["api_key"] = existing.api_key
    if not existing and not data.get("api_key"):
        raise HTTPException(status_code=400, detail="api_key is required for the initial setup")

    provider_connection_changed = (
        not existing
        or ("base_url" in data and str(data["base_url"]) != str(existing.base_url))
        or ("embedding_model" in data and str(data["embedding_model"]) != str(existing.embedding_model))
        or (
            incoming_key is not None
            and str(incoming_key).strip() != ""
            and str(incoming_key) != masked_existing
        )
    )

    probe_key = (
        str(incoming_key)
        if incoming_key and str(incoming_key).strip() and str(incoming_key) != masked_existing
        else AdminRepository.provider_api_key_plain(existing)
    )
    if provider_connection_changed and probe_key:
        await _verify_embedding_dimension(
            base_url=str(data.get("base_url", existing.base_url if existing else "")),
            api_key=probe_key,
            embedding_model=str(data.get("embedding_model", existing.embedding_model if existing else "")),
            timeout_s=int(data.get("timeout_s", existing.timeout_s if existing else settings.provider_timeout_s)),
        )

    try:
        row = repo.upsert_provider(ctx.tenant_id, data)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "upsert", "provider_settings", str(row.id), {"model": row.model_name})
    return ProviderSettingsOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        base_url=row.base_url,
        api_key=_mask_secret(AdminRepository.provider_api_key_plain(row)),
        model_name=row.model_name,
        embedding_model=row.embedding_model,
        timeout_s=row.timeout_s,
        retry_policy=row.retry_policy,
        knowledge_mode=row.knowledge_mode,
        empty_retrieval_mode=row.empty_retrieval_mode,
        strict_glossary_mode=row.strict_glossary_mode,
        show_confidence=row.show_confidence,
        show_source_tags=row.show_source_tags,
        response_tone=row.response_tone,
        max_user_messages_total=row.max_user_messages_total,
        chat_context_enabled=row.chat_context_enabled,
        history_user_turn_limit=row.history_user_turn_limit,
        history_message_limit=row.history_message_limit,
        history_token_budget=row.history_token_budget,
        rewrite_history_message_limit=row.rewrite_history_message_limit,
        updated_at=row.updated_at,
    )


@router.get("/logs", response_model=list[LogOut])
def list_logs(ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    rows = repo.list_error_logs(ctx.tenant_id)
    return [
        LogOut(id=str(r.id), created_at=r.created_at, type=r.error_type, message=r.message)
        for r in rows
    ]


@router.get("/traces", response_model=list[TraceOut])
def list_traces(ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    rows = repo.list_traces(ctx.tenant_id)
    return [
        TraceOut(
            id=str(r.id),
            chat_id=str(r.chat_id),
            model=r.model,
            knowledge_mode=r.knowledge_mode,
            answer_mode=r.answer_mode,
            source_types=r.source_types,
            glossary_entries_used=r.glossary_entries_used,
            document_ids=r.document_ids,
            web_snapshot_ids=r.web_snapshot_ids,
            web_domains_used=r.web_domains_used,
            ranking_scores=r.ranking_scores,
            latency_ms=r.latency_ms,
            token_usage=r.token_usage,
            chat_context_enabled=bool((r.token_usage or {}).get("chat_context_enabled", True)),
            rewrite_used=bool((r.token_usage or {}).get("rewrite_used", False)),
            rewritten_query=(r.token_usage or {}).get("rewritten_query"),
            history_messages_used=int((r.token_usage or {}).get("history_messages_used", 0) or 0),
            history_token_estimate=int((r.token_usage or {}).get("history_token_estimate", 0) or 0),
            history_trimmed=bool((r.token_usage or {}).get("history_trimmed", False)),
            status=r.status,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    source_type: str | None = None,
    status: str | None = None,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    return [
        _to_document_schema(
            row,
            chunk_count=chunk_count,
            latest_job=_latest_document_job(repo, ctx.tenant_id, str(row.id)),
        )
        for row, chunk_count in repo.list_documents(ctx.tenant_id, source_type=source_type, status=status)
    ]


@router.post("/documents/upload", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    enabled_in_retrieval: bool = Form(default=True),
    metadata_json: str | None = Form(default=None),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    try:
        payload = DocumentUploadForm.from_form(title, enabled_in_retrieval, metadata_json)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    service = DocumentService(db)
    row, job_id = await service.create_upload(ctx.tenant_id, ctx.user_id, file, payload)
    _schedule_document_ingestion(background_tasks, job_id)
    repo = AdminRepository(db)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, str(row.id))
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, str(row.id))
    repo.add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "upload",
        "document",
        str(row.id),
        {"title": row.title, "file_name": row.file_name},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(document_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    result = repo.get_document_with_chunk_count(ctx.tenant_id, document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    row, chunk_count = result
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id)
    return DocumentDetailOut(
        **_to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job).model_dump(),
        chunks=[_to_document_chunk_schema(chunk) for chunk in repo.list_document_chunks(ctx.tenant_id, document_id)],
    )


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: str,
    payload: DocumentUpdateIn,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    row = repo.get_document(ctx.tenant_id, document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.enabled_in_retrieval is None and payload.metadata_json is None:
        raise HTTPException(status_code=400, detail="Provide enabled_in_retrieval or metadata_json")
    service = DocumentService(db)
    if payload.metadata_json is not None:
        row = service.update_document_metadata(row, payload.metadata_json)
    if payload.enabled_in_retrieval is not None:
        row = service.set_enabled_in_retrieval(row, payload.enabled_in_retrieval)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id)
    repo.add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "toggle_retrieval",
        "document",
        document_id,
        {"enabled_in_retrieval": row.enabled_in_retrieval, "metadata_json": row.metadata_json or {}},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/sites", response_model=DocumentOut)
async def create_website_snapshot(
    payload: WebsiteSnapshotCreate,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    service = DocumentService(db)
    row, job_id = await service.create_website_snapshot(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        url=str(payload.url),
        title=payload.title,
        enabled_in_retrieval=payload.enabled_in_retrieval,
        tags=payload.tags,
    )
    _schedule_document_ingestion(background_tasks, job_id)
    repo = AdminRepository(db)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, str(row.id))
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, str(row.id))
    repo.add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "create",
        "website_snapshot",
        str(row.id),
        {"url": str(payload.url), "title": row.title},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/documents/{document_id}/approve", response_model=DocumentOut)
def approve_document(document_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    row = repo.get_document(ctx.tenant_id, document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    row = DocumentService(db).approve_document(row, ctx.user_id)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id)
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "approve", "document", document_id, {"status": row.status})
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/documents/{document_id}/archive", response_model=DocumentOut)
def archive_document(document_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    row = repo.get_document(ctx.tenant_id, document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    row = DocumentService(db).archive_document(row)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id)
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "archive", "document", document_id, {"status": row.status})
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    row = repo.get_document(ctx.tenant_id, document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    service = DocumentService(db)
    try:
        job_id = service.queue_reindex(row, ctx.user_id)
        _schedule_document_ingestion(background_tasks, job_id)
        row = repo.get_document(ctx.tenant_id, document_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to start document reindexing") from exc
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id)
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "reindex", "document", document_id, {"status": row.status})
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    row = repo.get_document(ctx.tenant_id, document_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    DocumentService(db).delete_document(row)
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "delete", "document", document_id, {})
    return {"detail": "Deleted"}


@router.get("/registrations/pending", response_model=list[PendingRegistrationOut])
async def list_pending_registrations(ctx: AuthContext = Depends(require_admin)):
    token = await _keycloak_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    users_url = f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/users"
    params = {"enabled": "false", "max": "500"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(users_url, headers=headers, params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Failed to fetch pending registrations")
    users = resp.json() or []
    result: list[PendingRegistrationOut] = []
    for user in users:
        tenant_id = _extract_user_tenant_id(user)
        if tenant_id != ctx.tenant_id:
            continue
        result.append(
            PendingRegistrationOut(
                id=str(user.get("id")),
                username=str(user.get("username") or ""),
                email=user.get("email"),
                tenant_id=tenant_id,
                enabled=bool(user.get("enabled")),
                created_at=_created_at_from_ms(user.get("createdTimestamp")),
            )
        )
    result.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return result


@router.post("/registrations/{user_id}/approve")
async def approve_registration(user_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    token = await _keycloak_admin_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    user_url = f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/users/{user_id}"

    async with httpx.AsyncClient(timeout=20) as client:
        user_resp = await client.get(user_url, headers=headers)
        if user_resp.status_code == 404:
            raise HTTPException(status_code=404, detail="User not found")
        if user_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Failed to fetch Keycloak user")

        user_data = user_resp.json()
        tenant_id = _extract_user_tenant_id(user_data)
        if tenant_id != ctx.tenant_id:
            raise HTTPException(status_code=404, detail="User not found")

        user_data["enabled"] = True
        required_actions = user_data.get("requiredActions") or []
        user_data["requiredActions"] = [x for x in required_actions if x != "VERIFY_EMAIL"]
        update_resp = await client.put(user_url, headers=headers, json=user_data)
        if update_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Failed to approve user")

    repo = AdminRepository(db)
    repo.add_audit_log(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="approve_registration",
        entity_type="keycloak_user",
        entity_id=user_id,
        payload={"tenant_id": ctx.tenant_id},
    )
    return {"detail": "User approved"}
