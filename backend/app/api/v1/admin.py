from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import db_dep
from app.core.config import get_settings
from app.core.security import AuthContext, require_admin
from app.repositories.admin_repository import AdminRepository
from app.schemas.admin import (
    AllowlistDomainCreate,
    AllowlistDomainOut,
    AllowlistDomainUpdate,
    LogOut,
    ProviderSettingsIn,
    ProviderSettingsOut,
    PendingRegistrationOut,
    TraceOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


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


async def _keycloak_admin_token() -> str:
    if not settings.keycloak_admin or not settings.keycloak_admin_password:
        raise HTTPException(status_code=500, detail="Не настроены KEYCLOAK_ADMIN/KEYCLOAK_ADMIN_PASSWORD")
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
        raise HTTPException(status_code=502, detail="Не удалось получить admin token Keycloak")
    token = resp.json().get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="Keycloak admin token пустой")
    return str(token)


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
        max_user_messages_total=row.max_user_messages_total,
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
        max_user_messages_total=row.max_user_messages_total,
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


@router.get("/registrations/pending", response_model=list[PendingRegistrationOut])
async def list_pending_registrations(ctx: AuthContext = Depends(require_admin)):
    token = await _keycloak_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    users_url = f"{settings.keycloak_server_url}/admin/realms/{settings.keycloak_realm}/users"
    params = {"enabled": "false", "max": "500"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(users_url, headers=headers, params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Не удалось получить список pending-регистраций")
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
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if user_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Не удалось получить пользователя Keycloak")

        user_data = user_resp.json()
        tenant_id = _extract_user_tenant_id(user_data)
        if tenant_id != ctx.tenant_id:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        user_data["enabled"] = True
        required_actions = user_data.get("requiredActions") or []
        user_data["requiredActions"] = [x for x in required_actions if x != "VERIFY_EMAIL"]
        update_resp = await client.put(user_url, headers=headers, json=user_data)
        if update_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Не удалось подтвердить пользователя")

    repo = AdminRepository(db)
    repo.add_audit_log(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        action="approve_registration",
        entity_type="keycloak_user",
        entity_id=user_id,
        payload={"tenant_id": ctx.tenant_id},
    )
    return {"detail": "Пользователь подтвержден"}
