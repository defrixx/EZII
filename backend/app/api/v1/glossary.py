import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_dep
from app.core.security import AuthContext, require_admin
from app.repositories.admin_repository import AdminRepository
from app.repositories.glossary_repository import GlossaryRepository
from app.schemas.glossary import (
    GlossaryCreate,
    GlossaryEntryCreate,
    GlossaryEntryOut,
    GlossaryEntryUpdate,
    GlossaryExportResponse,
    GlossaryImportRequest,
    GlossaryOut,
    GlossaryUpdate,
)
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/glossary", tags=["glossary"])


def _entry_text(term: str, definition: str) -> str:
    return f"{term}\n{definition}"


def _to_glossary_schema(r) -> GlossaryOut:
    return GlossaryOut(
        id=str(r.id),
        tenant_id=str(r.tenant_id),
        name=r.name,
        description=r.description,
        priority=r.priority,
        enabled=r.enabled,
        is_default=r.is_default,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _to_entry_schema(r) -> GlossaryEntryOut:
    return GlossaryEntryOut(
        id=str(r.id),
        tenant_id=str(r.tenant_id),
        glossary_id=str(r.glossary_id),
        term=r.term,
        definition=r.definition,
        example=r.example,
        synonyms=r.synonyms or [],
        forbidden_interpretations=r.forbidden_interpretations or [],
        owner=r.owner,
        version=r.version,
        priority=r.priority,
        status=r.status,
        created_at=r.created_at,
        updated_at=r.updated_at,
        created_by=r.created_by,
        metadata_json=r.metadata_json,
    )


@router.get("", response_model=list[GlossaryOut])
def list_glossaries(ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = GlossaryRepository(db)
    return [_to_glossary_schema(r) for r in repo.list_glossaries(ctx.tenant_id)]


@router.post("", response_model=GlossaryOut)
def create_glossary(payload: GlossaryCreate, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = GlossaryRepository(db)
    row = repo.create_glossary(ctx.tenant_id, payload.model_dump())
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "create", "glossary", str(row.id), {"name": row.name})
    return _to_glossary_schema(row)


@router.patch("/{glossary_id}", response_model=GlossaryOut)
def update_glossary(
    glossary_id: str,
    payload: GlossaryUpdate,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = GlossaryRepository(db)
    row = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not row:
        raise HTTPException(status_code=404, detail="Глоссарий не найден")
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if row.is_default and "enabled" in data and data["enabled"] is False:
        raise HTTPException(status_code=400, detail="Глоссарий по умолчанию нельзя отключить")
    row = repo.update_glossary(row, data)
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "update", "glossary", str(row.id), {"name": row.name})
    return _to_glossary_schema(row)


@router.delete("/{glossary_id}")
def delete_glossary(glossary_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = GlossaryRepository(db)
    row = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not row:
        raise HTTPException(status_code=404, detail="Глоссарий не найден")
    if row.is_default:
        raise HTTPException(status_code=400, detail="Глоссарий по умолчанию нельзя удалить")
    retrieval = RetrievalService(db)
    for entry in repo.list_entries(ctx.tenant_id, glossary_id):
        try:
            retrieval.vector.delete_entry(str(entry.id))
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Не удалось удалить записи из векторного индекса") from exc
    repo.delete_glossary(row)
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "delete", "glossary", glossary_id, {})
    return {"detail": "Удалено"}


@router.get("/{glossary_id}/entries", response_model=list[GlossaryEntryOut])
def list_entries(glossary_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Глоссарий не найден")
    return [_to_entry_schema(r) for r in repo.list_entries(ctx.tenant_id, glossary_id)]


@router.post("/{glossary_id}/entries", response_model=GlossaryEntryOut)
def create_entry(
    glossary_id: str,
    payload: GlossaryEntryCreate,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Глоссарий не найден")

    row = repo.create_entry(ctx.tenant_id, glossary_id, ctx.user_id, payload.model_dump(), auto_commit=False)

    retrieval = RetrievalService(db)
    try:
        provider = retrieval._provider_for_tenant(ctx.tenant_id)
        emb = asyncio.run(provider.embeddings([_entry_text(row.term, row.definition)]))
        if not emb:
            raise RuntimeError("empty embedding response")
        retrieval.vector.upsert_entry(
            str(row.id),
            ctx.tenant_id,
            emb[0],
            {
                "term": row.term,
                "definition": row.definition,
                "glossary_id": str(glossary.id),
                "glossary_name": glossary.name,
                "glossary_priority": glossary.priority,
                "entry_priority": row.priority,
            },
        )
    except Exception as exc:
        db.rollback()
        try:
            retrieval.vector.delete_entry(str(row.id))
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="Не удалось синхронизировать запись с векторным индексом") from exc
    db.commit()

    AdminRepository(db).add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "create",
        "glossary_entry",
        str(row.id),
        {"term": row.term, "glossary_id": str(glossary.id)},
    )
    return _to_entry_schema(row)


@router.patch("/{glossary_id}/entries/{entry_id}", response_model=GlossaryEntryOut)
def update_entry(
    glossary_id: str,
    entry_id: str,
    payload: GlossaryEntryUpdate,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Глоссарий не найден")
    row = repo.get_entry(ctx.tenant_id, glossary_id, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Запись глоссария не найдена")

    retrieval = RetrievalService(db)
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    next_term = patch.get("term", row.term)
    next_definition = patch.get("definition", row.definition)
    try:
        provider = retrieval._provider_for_tenant(ctx.tenant_id)
        emb = asyncio.run(provider.embeddings([_entry_text(next_term, next_definition)]))
        if not emb:
            raise RuntimeError("empty embedding response")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось обновить эмбеддинг для записи") from exc

    row = repo.update_entry(row, patch, auto_commit=False)
    try:
        retrieval.vector.upsert_entry(
            str(row.id),
            ctx.tenant_id,
            emb[0],
            {
                "term": row.term,
                "definition": row.definition,
                "glossary_id": str(glossary.id),
                "glossary_name": glossary.name,
                "glossary_priority": glossary.priority,
                "entry_priority": row.priority,
            },
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="Не удалось синхронизировать обновление с векторным индексом") from exc
    db.commit()

    AdminRepository(db).add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "update",
        "glossary_entry",
        str(row.id),
        {"term": row.term, "glossary_id": str(glossary.id)},
    )
    return _to_entry_schema(row)


@router.delete("/{glossary_id}/entries/{entry_id}")
def delete_entry(glossary_id: str, entry_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = GlossaryRepository(db)
    row = repo.get_entry(ctx.tenant_id, glossary_id, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Запись глоссария не найдена")
    retrieval = RetrievalService(db)
    try:
        retrieval.vector.delete_entry(entry_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось удалить запись из векторного индекса") from exc
    repo.delete_entry(row, auto_commit=False)
    db.commit()
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "delete", "glossary_entry", entry_id, {})
    return {"detail": "Удалено"}


@router.post("/{glossary_id}/import")
def import_entries(
    glossary_id: str,
    payload: GlossaryImportRequest,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Глоссарий не найден")

    created = 0
    created_rows = []
    retrieval = RetrievalService(db)
    provider = retrieval._provider_for_tenant(ctx.tenant_id)
    for row in payload.rows:
        created_row = repo.create_entry(ctx.tenant_id, glossary_id, ctx.user_id, row.model_dump(), auto_commit=False)
        created_rows.append(created_row)
        try:
            embeddings = asyncio.run(provider.embeddings([_entry_text(created_row.term, created_row.definition)]))
            if not embeddings:
                raise RuntimeError("empty embedding response")
            retrieval.vector.upsert_entry(
                str(created_row.id),
                ctx.tenant_id,
                embeddings[0],
                {
                    "term": created_row.term,
                    "definition": created_row.definition,
                    "glossary_id": str(glossary.id),
                    "glossary_name": glossary.name,
                    "glossary_priority": glossary.priority,
                    "entry_priority": created_row.priority,
                },
            )
            created += 1
        except Exception as exc:
            db.rollback()
            for rollback_row in created_rows:
                try:
                    retrieval.vector.delete_entry(str(rollback_row.id))
                except Exception:
                    pass
            raise HTTPException(status_code=502, detail="Импорт отменен: ошибка синхронизации с векторным индексом") from exc
    db.commit()
    AdminRepository(db).add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "import",
        "glossary_entry",
        "bulk",
        {"count": created, "glossary_id": glossary_id},
    )
    return {"created": created}


@router.get("/{glossary_id}/export", response_model=GlossaryExportResponse)
def export_entries(glossary_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Глоссарий не найден")

    rows = [_to_entry_schema(r) for r in repo.list_entries(ctx.tenant_id, glossary_id)]
    return GlossaryExportResponse(rows=rows)
