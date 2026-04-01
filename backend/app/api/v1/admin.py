import asyncio
from datetime import datetime, timezone
import ipaddress
import logging
import socket
from typing import Any
from uuid import UUID
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.api.deps import db_dep
from app.api.v1.auth import enforce_csrf_for_cookie_auth
from app.core.config import get_settings
from app.core.security import AuthContext, require_admin
from app.repositories.admin_repository import AdminRepository
from app.services.document_service import DocumentService
from app.services.provider_service import OpenRouterProvider
from app.schemas.admin import (
    DocumentChunkOut,
    DocumentDetailOut,
    DocumentListOut,
    DocumentOut,
    DocumentUploadForm,
    DocumentUpdateIn,
    LogOut,
    PendingRegistrationOut,
    ProviderSettingsIn,
    ProviderSettingsOut,
    QdrantResetAllIn,
    QdrantResetAllOut,
    SourceImpactOut,
    TraceOut,
    UserTokenUsagePageOut,
    WebsiteSnapshotCreate,
    validate_document_metadata_json,
)

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()
logger = logging.getLogger(__name__)
QDRANT_RESET_CONFIRM_PHRASE = "DELETE ALL QDRANT COLLECTIONS"


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "*" * len(secret)
    return f"{'*' * 12}{secret[-4:]}"


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
        model=embedding_model,
        embedding_model=embedding_model,
        timeout_s=timeout_s,
        max_retries=0,
        embedding_base_url=settings.embeddings_base_url or None,
        embedding_api_key=settings.embeddings_api_token or None,
        embedding_oauth_url=settings.embeddings_oauth_url or None,
        embedding_oauth_scope=settings.embeddings_oauth_scope or None,
        embedding_ca_bundle_path=settings.embeddings_ca_bundle_path or None,
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


def _schedule_document_ingestion(background_tasks: BackgroundTasks, tenant_id: str, job_id: str) -> None:
    background_tasks.add_task(DocumentService.run_ingestion_job, tenant_id, job_id)


def _safe_add_audit_log(
    repo: AdminRepository,
    *,
    tenant_id: str,
    user_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    try:
        repo.add_audit_log(tenant_id, user_id, action, entity_type, entity_id, payload)
    except Exception as exc:
        logger.warning(
            "Audit log write failed tenant=%s action=%s entity_type=%s entity_id=%s: %s",
            tenant_id,
            action,
            entity_type,
            entity_id,
            str(exc)[:300],
        )


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


def _looks_like_fallback_email(email: str) -> bool:
    normalized = str(email or "").strip().lower()
    return normalized.endswith("@keycloak.local")


async def _resolve_user_emails_from_keycloak(user_ids: list[str], tenant_id: str) -> dict[str, str]:
    ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    if not ids:
        return {}
    try:
        token = await _keycloak_admin_token()
    except Exception as exc:
        logger.warning("Failed to get Keycloak token for email enrichment: %s", str(exc)[:200])
        return {}

    headers = {"Authorization": f"Bearer {token}"}
    users_base_url = f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/users"
    result: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=15) as client:
        requests = [client.get(f"{users_base_url}/{user_id}", headers=headers) for user_id in ids]
        responses = await asyncio.gather(*requests, return_exceptions=True)
    for user_id, response in zip(ids, responses):
        if isinstance(response, Exception):
            continue
        if response.status_code >= 400:
            continue
        try:
            payload = response.json() if response.content else {}
        except Exception:
            payload = {}
        raw_email = str(payload.get("email") or "").strip()
        if not raw_email:
            preferred_username = str(payload.get("preferredUsername") or payload.get("username") or "").strip()
            if "@" in preferred_username:
                raw_email = preferred_username
        if raw_email and not _looks_like_fallback_email(raw_email):
            result[user_id] = raw_email
    unresolved = [user_id for user_id in ids if user_id not in result]
    if not unresolved:
        return result

    unresolved_set = set(unresolved)
    async with httpx.AsyncClient(timeout=20) as client:
        page_size = 500
        first = 0
        while unresolved_set:
            resp = await client.get(
                users_base_url,
                headers=headers,
                params={"first": str(first), "max": str(page_size)},
            )
            if resp.status_code >= 400:
                break
            rows = resp.json() or []
            if not rows:
                break
            for user in rows:
                user_id = str(user.get("id") or "").strip()
                if user_id not in unresolved_set:
                    continue
                if _extract_user_tenant_id(user) != tenant_id:
                    continue
                raw_email = str(user.get("email") or "").strip()
                if not raw_email:
                    preferred_username = str(user.get("preferredUsername") or user.get("username") or "").strip()
                    if "@" in preferred_username:
                        raw_email = preferred_username
                if raw_email and not _looks_like_fallback_email(raw_email):
                    result[user_id] = raw_email
                    unresolved_set.remove(user_id)
            if len(rows) < page_size:
                break
            first += page_size

    return result


def _reset_all_qdrant_collections_sync(vector_size: int) -> tuple[list[str], list[str]]:
    client = QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout_s)
    collections = [c.name for c in client.get_collections().collections]
    for name in collections:
        client.delete_collection(collection_name=name)

    recreated = [settings.qdrant_collection, settings.qdrant_documents_collection]
    for name in recreated:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    return collections, recreated


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
async def put_provider(
    payload: ProviderSettingsIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
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
        try:
            await _verify_embedding_dimension(
                base_url=str(data.get("base_url", existing.base_url if existing else "")),
                api_key=probe_key,
                embedding_model=str(data.get("embedding_model", existing.embedding_model if existing else "")),
                timeout_s=int(data.get("timeout_s", existing.timeout_s if existing else settings.provider_timeout_s)),
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(
                "Embedding provider connectivity verification failed tenant=%s model=%s: %s",
                ctx.tenant_id,
                str(data.get("embedding_model", existing.embedding_model if existing else "")),
                str(exc)[:300],
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Failed to verify embedding provider connectivity. "
                    "Check EMBEDDINGS_CA_BUNDLE_PATH / server certificate chain for TLS trust."
                ),
            ) from exc

    try:
        row = repo.upsert_provider(ctx.tenant_id, data)
    except RuntimeError as exc:
        logger.exception("Failed to upsert provider settings tenant=%s: %s", ctx.tenant_id, str(exc)[:300])
        raise HTTPException(status_code=500, detail="Failed to update provider settings") from exc
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="upsert",
        entity_type="provider_settings",
        entity_id=str(row.id),
        payload={"model": row.model_name},
    )
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


@router.post("/qdrant/reset-all", response_model=QdrantResetAllOut)
async def reset_all_qdrant_collections(
    payload: QdrantResetAllIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    if settings.default_tenant_id and ctx.tenant_id != settings.default_tenant_id:
        raise HTTPException(status_code=403, detail="Only the default tenant admin can run global Qdrant reset")
    if payload.confirm_phrase.strip() != QDRANT_RESET_CONFIRM_PHRASE:
        raise HTTPException(status_code=400, detail="Invalid first confirmation phrase")
    if payload.confirm_phrase_repeat.strip() != QDRANT_RESET_CONFIRM_PHRASE:
        raise HTTPException(status_code=400, detail="Invalid second confirmation phrase")

    try:
        deleted, recreated = await run_in_threadpool(
            _reset_all_qdrant_collections_sync,
            payload.embedding_vector_size,
        )
    except Exception as exc:
        logger.exception(
            "Qdrant reset-all failed tenant=%s vector_size=%s: %s",
            ctx.tenant_id,
            payload.embedding_vector_size,
            str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="Failed to reset Qdrant collections") from exc

    repo = AdminRepository(db)
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="reset_all_qdrant_collections",
        entity_type="qdrant",
        entity_id="global",
        payload={
            "deleted_collections_count": len(deleted),
            "recreated_collections": recreated,
            "embedding_vector_size": payload.embedding_vector_size,
        },
    )
    return QdrantResetAllOut(
        deleted_collections=deleted,
        recreated_collections=recreated,
        embedding_vector_size=payload.embedding_vector_size,
    )


@router.get("/logs", response_model=list[LogOut])
def list_logs(
    limit: int = Query(default=20, ge=1, le=200),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    rows = repo.list_error_logs(ctx.tenant_id, limit=limit)
    return [
        LogOut(id=str(r.id), created_at=r.created_at, type=r.error_type, message=r.message)
        for r in rows
    ]


@router.get("/traces", response_model=list[TraceOut])
def list_traces(
    limit: int = Query(default=20, ge=1, le=200),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    rows = repo.list_traces(ctx.tenant_id, limit=limit)
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


@router.get("/analytics/source-impact", response_model=SourceImpactOut)
def source_impact_analytics(
    window_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=100),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    return SourceImpactOut.model_validate(
        repo.source_impact_analytics(
            ctx.tenant_id,
            window_days=window_days,
            limit=limit,
        )
    )


@router.get("/analytics/token-usage/users", response_model=UserTokenUsagePageOut)
async def user_token_usage_analytics(
    window_days: int = Query(default=30, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    payload = repo.user_token_usage_analytics(
        ctx.tenant_id,
        window_days=window_days,
        page=page,
        page_size=page_size,
        sort_order=sort_order,
    )
    items = payload.get("items") or []
    fallback_ids = [
        str(item.get("user_id") or "")
        for item in items
        if _looks_like_fallback_email(str(item.get("email") or ""))
    ]
    if fallback_ids:
        resolved_emails = await _resolve_user_emails_from_keycloak(fallback_ids, ctx.tenant_id)
        if resolved_emails:
            for item in items:
                user_id = str(item.get("user_id") or "")
                if user_id in resolved_emails:
                    item["email"] = resolved_emails[user_id]
    return UserTokenUsagePageOut.model_validate(payload)


@router.get("/documents", response_model=DocumentListOut)
def list_documents(
    source_type: str | None = None,
    status: str | None = None,
    unused_only: bool = Query(default=False),
    unused_window_days: int = Query(default=30, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = None,
    tag: str | None = None,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    rows, total = repo.list_documents(
        ctx.tenant_id,
        source_type=source_type,
        status=status,
        search=search,
        tag=tag,
        unused_only=unused_only,
        unused_window_days=unused_window_days,
        page=page,
        page_size=page_size,
    )
    return DocumentListOut(
        items=[
            _to_document_schema(
                row,
                chunk_count=chunk_count,
                latest_job=_latest_document_job(repo, ctx.tenant_id, str(row.id)),
            )
            for row, chunk_count in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/documents/tags", response_model=list[str])
def list_document_tags(
    source_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    return repo.list_document_tags(
        ctx.tenant_id,
        source_type=source_type,
        status=status,
        search=search,
        limit=limit,
    )


@router.post("/documents/upload", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    enabled_in_retrieval: bool = Form(default=True),
    metadata_json: str | None = Form(default=None),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    try:
        payload = DocumentUploadForm.from_form(title, enabled_in_retrieval, metadata_json)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    service = DocumentService(db)
    row, job_id = await service.create_upload(ctx.tenant_id, ctx.user_id, file, payload)
    _schedule_document_ingestion(background_tasks, ctx.tenant_id, job_id)
    repo = AdminRepository(db)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, str(row.id))
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, str(row.id))
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="upload",
        entity_type="document",
        entity_id=str(row.id),
        payload={"title": row.title, "file_name": row.file_name},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(document_id: UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    document_id_str = str(document_id)
    result = repo.get_document_with_chunk_count(ctx.tenant_id, document_id_str)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    row, chunk_count = result
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id_str)
    return DocumentDetailOut(
        **_to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job).model_dump(),
        chunks=[_to_document_chunk_schema(chunk) for chunk in repo.list_document_chunks(ctx.tenant_id, document_id_str)],
    )


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: UUID,
    payload: DocumentUpdateIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = AdminRepository(db)
    document_id_str = str(document_id)
    row = repo.get_document(ctx.tenant_id, document_id_str)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.enabled_in_retrieval is None and payload.metadata_json is None:
        raise HTTPException(status_code=400, detail="Provide enabled_in_retrieval or metadata_json")
    service = DocumentService(db)
    if payload.metadata_json is not None and payload.enabled_in_retrieval is not None:
        merged = dict(row.metadata_json or {})
        merged.update(payload.metadata_json)
        repo.update_document(row, {"metadata_json": validate_document_metadata_json(merged)}, auto_commit=False)
        row = service.set_enabled_in_retrieval(row, payload.enabled_in_retrieval)
    elif payload.metadata_json is not None:
        row = service.update_document_metadata(row, payload.metadata_json)
    elif payload.enabled_in_retrieval is not None:
        row = service.set_enabled_in_retrieval(row, payload.enabled_in_retrieval)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id_str)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id_str)
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="toggle_retrieval",
        entity_type="document",
        entity_id=document_id_str,
        payload={"enabled_in_retrieval": row.enabled_in_retrieval, "metadata_json": row.metadata_json or {}},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/sites", response_model=DocumentOut)
async def create_website_snapshot(
    payload: WebsiteSnapshotCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    service = DocumentService(db)
    row, job_id = await service.create_website_snapshot(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        url=str(payload.url),
        title=payload.title,
        enabled_in_retrieval=payload.enabled_in_retrieval,
        tags=payload.tags,
    )
    _schedule_document_ingestion(background_tasks, ctx.tenant_id, job_id)
    repo = AdminRepository(db)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, str(row.id))
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, str(row.id))
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="create",
        entity_type="website_snapshot",
        entity_id=str(row.id),
        payload={"url": str(payload.url), "title": row.title},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/documents/{document_id}/approve", response_model=DocumentOut)
def approve_document(
    document_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = AdminRepository(db)
    document_id_str = str(document_id)
    row = repo.get_document(ctx.tenant_id, document_id_str)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    row = DocumentService(db).approve_document(row, ctx.user_id)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id_str)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id_str)
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="approve",
        entity_type="document",
        entity_id=document_id_str,
        payload={"status": row.status},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/documents/{document_id}/archive", response_model=DocumentOut)
def archive_document(
    document_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = AdminRepository(db)
    document_id_str = str(document_id)
    row = repo.get_document(ctx.tenant_id, document_id_str)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    row = DocumentService(db).archive_document(row)
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id_str)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id_str)
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="archive",
        entity_type="document",
        entity_id=document_id_str,
        payload={"status": row.status},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = AdminRepository(db)
    document_id_str = str(document_id)
    row = repo.get_document(ctx.tenant_id, document_id_str)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    service = DocumentService(db)
    try:
        job_id = service.queue_reindex(row, ctx.user_id)
        _schedule_document_ingestion(background_tasks, ctx.tenant_id, job_id)
        row = repo.get_document(ctx.tenant_id, document_id_str)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to start document reindexing") from exc
    count_row = repo.get_document_with_chunk_count(ctx.tenant_id, document_id_str)
    chunk_count = int(count_row[1]) if count_row else 0
    latest_job = _latest_document_job(repo, ctx.tenant_id, document_id_str)
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="reindex",
        entity_type="document",
        entity_id=document_id_str,
        payload={"status": row.status},
    )
    return _to_document_schema(row, chunk_count=chunk_count, latest_job=latest_job)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = AdminRepository(db)
    document_id_str = str(document_id)
    row = repo.get_document(ctx.tenant_id, document_id_str)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    DocumentService(db).delete_document(row)
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="delete",
        entity_type="document",
        entity_id=document_id_str,
        payload={},
    )
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
async def approve_registration(
    user_id: str,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
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
    _safe_add_audit_log(
        repo,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="approve_registration",
        entity_type="keycloak_user",
        entity_id=user_id,
        payload={"tenant_id": ctx.tenant_id},
    )
    return {"detail": "User approved"}
