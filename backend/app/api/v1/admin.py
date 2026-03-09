from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import db_dep
from app.core.security import AuthContext, require_admin
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import (
    AllowlistDomainCreate,
    AllowlistDomainOut,
    AllowlistDomainUpdate,
    LogOut,
    ProviderSettingsIn,
    ProviderSettingsOut,
    RetrievalTestRequest,
    RetrievalTestResponse,
    TraceOut,
)
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/admin", tags=["admin"])


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


@router.get("/allowlist", response_model=list[AllowlistDomainOut])
def list_allowlist(ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    rows = repo.list_allowlist(ctx.tenant_id)
    return [
        AllowlistDomainOut(
            id=str(r.id),
            domain=r.domain,
            notes=r.notes,
            enabled=r.enabled,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/allowlist", response_model=AllowlistDomainOut)
def create_allowlist(payload: AllowlistDomainCreate, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    row = repo.create_allowlist(ctx.tenant_id, payload.domain, payload.notes, payload.enabled)
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "create", "allowlist_domain", str(row.id), {"domain": row.domain})
    return AllowlistDomainOut(
        id=str(row.id),
        domain=row.domain,
        notes=row.notes,
        enabled=row.enabled,
        created_at=row.created_at,
    )


@router.delete("/allowlist/{domain_id}")
def delete_allowlist(domain_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    if not repo.delete_allowlist(ctx.tenant_id, domain_id):
        raise HTTPException(status_code=404, detail="Домен не найден")
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "delete", "allowlist_domain", domain_id, {})
    return {"detail": "Удалено"}


@router.patch("/allowlist/{domain_id}", response_model=AllowlistDomainOut)
def update_allowlist(
    domain_id: str,
    payload: AllowlistDomainUpdate,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = AdminRepository(db)
    row = repo.update_allowlist(
        ctx.tenant_id,
        domain_id,
        domain=payload.domain if payload.domain is not None else None,
        notes=payload.notes,
        enabled=payload.enabled,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Домен не найден")
    repo.add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "update",
        "allowlist_domain",
        str(row.id),
        {"domain": row.domain, "notes": row.notes, "enabled": row.enabled},
    )
    return AllowlistDomainOut(
        id=str(row.id),
        domain=row.domain,
        notes=row.notes,
        enabled=row.enabled,
        created_at=row.created_at,
    )


@router.get("/provider", response_model=ProviderSettingsOut)
def get_provider(ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    row = repo.get_provider(ctx.tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Настройки провайдера не сконфигурированы")
    return ProviderSettingsOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        base_url=row.base_url,
        api_key=_mask_secret(row.api_key),
        model_name=row.model_name,
        embedding_model=row.embedding_model,
        timeout_s=row.timeout_s,
        retry_policy=row.retry_policy,
        strict_glossary_mode=row.strict_glossary_mode,
        web_enabled=row.web_enabled,
        show_confidence=row.show_confidence,
        show_source_tags=row.show_source_tags,
        response_tone=row.response_tone,
        updated_at=row.updated_at,
    )


@router.put("/provider", response_model=ProviderSettingsOut)
def put_provider(payload: ProviderSettingsIn, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = AdminRepository(db)
    existing = repo.get_provider(ctx.tenant_id)
    data = payload.model_dump(exclude_none=True)
    if "base_url" in data:
        data["base_url"] = str(data["base_url"])
    incoming_key = data.get("api_key")
    if existing and (not incoming_key or "*" in incoming_key):
        data["api_key"] = existing.api_key
    if not existing and not data.get("api_key"):
        raise HTTPException(status_code=400, detail="api_key обязателен при первичной настройке")
    row = repo.upsert_provider(ctx.tenant_id, data)
    repo.add_audit_log(ctx.tenant_id, ctx.user_id, "upsert", "provider_settings", str(row.id), {"model": row.model_name})
    return ProviderSettingsOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        base_url=row.base_url,
        api_key=_mask_secret(row.api_key),
        model_name=row.model_name,
        embedding_model=row.embedding_model,
        timeout_s=row.timeout_s,
        retry_policy=row.retry_policy,
        strict_glossary_mode=row.strict_glossary_mode,
        web_enabled=row.web_enabled,
        show_confidence=row.show_confidence,
        show_source_tags=row.show_source_tags,
        response_tone=row.response_tone,
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
            glossary_entries_used=r.glossary_entries_used,
            web_domains_used=r.web_domains_used,
            ranking_scores=r.ranking_scores,
            latency_ms=r.latency_ms,
            token_usage=r.token_usage,
            status=r.status,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/retrieval-test", response_model=RetrievalTestResponse)
async def retrieval_test(payload: RetrievalTestRequest, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    retrieval = RetrievalService(db)
    res = await retrieval.run(
        tenant_id=ctx.tenant_id,
        query=payload.query,
        strict_glossary_mode=payload.strict_glossary_mode,
        web_enabled=payload.web_enabled,
    )
    return RetrievalTestResponse(
        normalized_query=res["normalized_query"],
        top_glossary=res["top_glossary"],
        web_domains_used=res["web_domains_used"],
        assembled_context=res["assembled_context"],
    )
