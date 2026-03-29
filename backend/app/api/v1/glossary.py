import asyncio
import csv
import inspect
import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import db_dep
from app.api.v1.auth import enforce_csrf_for_cookie_auth
from app.core.config import get_settings
from app.core.security import AuthContext, require_admin
from app.repositories.admin_repository import AdminRepository
from app.repositories.glossary_repository import GlossaryRepository
from app.schemas.glossary import (
    GlossaryCsvImportResult,
    GlossaryCreate,
    GlossaryEntryCreate,
    GlossaryEntryOut,
    GlossaryEntryUpdate,
    GlossaryImportRow,
    GlossaryOut,
    GlossaryUpdate,
)
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/glossary", tags=["glossary"])
settings = get_settings()
logger = logging.getLogger(__name__)
CSV_REQUIRED_HEADERS = {"term", "definition"}
CSV_OPTIONAL_HEADERS = {
    "example",
    "synonyms",
    "forbidden_interpretations",
    "owner",
    "version",
    "priority",
    "status",
    "metadata_json",
    "tags",
}
CSV_ALLOWED_HEADERS = CSV_REQUIRED_HEADERS | CSV_OPTIONAL_HEADERS


def _entry_text(term: str, definition: str) -> str:
    return f"{term}\n{definition}"


def _supports_auto_commit(callable_obj) -> bool:
    try:
        return "auto_commit" in inspect.signature(callable_obj).parameters
    except Exception:
        return False


def _safe_commit(db: Session) -> None:
    commit = getattr(db, "commit", None)
    if callable(commit):
        commit()


def _safe_rollback(db: Session) -> None:
    rollback = getattr(db, "rollback", None)
    if callable(rollback):
        rollback()


def _repo_create_entry(repo: GlossaryRepository, tenant_id: str, glossary_id: str, created_by: str, payload: dict):
    if _supports_auto_commit(repo.create_entry):
        return repo.create_entry(tenant_id, glossary_id, created_by, payload, auto_commit=False)
    return repo.create_entry(tenant_id, glossary_id, created_by, payload)


def _repo_update_entry(repo: GlossaryRepository, row, payload: dict):
    if _supports_auto_commit(repo.update_entry):
        return repo.update_entry(row, payload, auto_commit=False)
    return repo.update_entry(row, payload)


def _repo_delete_entry(repo: GlossaryRepository, row) -> None:
    if _supports_auto_commit(repo.delete_entry):
        repo.delete_entry(row, auto_commit=False)
        return
    repo.delete_entry(row)


def _csv_list(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").split(";") if item.strip()]


def _normalize_csv_payload(row: dict[str, str]) -> dict:
    metadata_json = {}
    if row.get("metadata_json"):
        try:
            parsed = json.loads(row["metadata_json"])
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="metadata_json column must contain a JSON object") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="metadata_json column must contain a JSON object")
        metadata_json = parsed
    tags = _csv_list(row.get("tags"))
    if tags:
        metadata_json = {**metadata_json, "tags": tags}
    return {
        "term": (row.get("term") or "").strip(),
        "definition": (row.get("definition") or "").strip(),
        "example": (row.get("example") or "").strip() or None,
        "synonyms": _csv_list(row.get("synonyms")),
        "forbidden_interpretations": _csv_list(row.get("forbidden_interpretations")),
        "owner": (row.get("owner") or "").strip() or None,
        "version": int((row.get("version") or "1").strip() or "1"),
        "priority": int((row.get("priority") or "100").strip() or "100"),
        "status": (row.get("status") or "active").strip() or "active",
        "metadata_json": metadata_json,
    }


def _parse_csv_import(file_name: str | None, raw_bytes: bytes) -> list[GlossaryImportRow]:
    if not (file_name or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    if len(raw_bytes) > int(settings.glossary_csv_import_max_bytes):
        raise HTTPException(status_code=413, detail="CSV file exceeds the 10 MB limit")

    decoded = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            decoded = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise HTTPException(status_code=400, detail="Failed to decode CSV file")

    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(decoded.splitlines(), dialect=dialect)
    fieldnames = set(reader.fieldnames or [])
    if not fieldnames:
        raise HTTPException(status_code=400, detail="CSV file does not contain headers")
    missing = sorted(CSV_REQUIRED_HEADERS - fieldnames)
    if missing:
        raise HTTPException(status_code=400, detail=f"CSV file must contain columns: {', '.join(sorted(CSV_REQUIRED_HEADERS))}")
    unknown = sorted(fieldnames - CSV_ALLOWED_HEADERS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown CSV columns: {', '.join(unknown)}")

    rows: list[GlossaryImportRow] = []
    for index, row in enumerate(reader, start=2):
        try:
            rows.append(GlossaryImportRow.model_validate(_normalize_csv_payload(row)))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"CSV error on row {index}: {exc}") from exc
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file does not contain rows to import")
    return rows


def _dedupe_import_rows_by_term(rows: list[GlossaryImportRow]) -> list[GlossaryImportRow]:
    deduped: dict[str, GlossaryImportRow] = {}
    for row in rows:
        key = row.term.strip().lower()
        deduped[key] = row
    return list(deduped.values())


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
def create_glossary(
    payload: GlossaryCreate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = GlossaryRepository(db)
    row = repo.create_glossary(ctx.tenant_id, payload.model_dump())
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "create", "glossary", str(row.id), {"name": row.name})
    return _to_glossary_schema(row)


@router.patch("/{glossary_id}", response_model=GlossaryOut)
def update_glossary(
    glossary_id: str,
    payload: GlossaryUpdate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = GlossaryRepository(db)
    row = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not row:
        raise HTTPException(status_code=404, detail="Glossary not found")
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if row.is_default and "enabled" in data and data["enabled"] is False:
        raise HTTPException(status_code=400, detail="The default glossary cannot be disabled")
    row = repo.update_glossary(row, data)
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "update", "glossary", str(row.id), {"name": row.name})
    return _to_glossary_schema(row)


@router.delete("/{glossary_id}")
def delete_glossary(
    glossary_id: str,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = GlossaryRepository(db)
    row = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not row:
        raise HTTPException(status_code=404, detail="Glossary not found")
    if row.is_default:
        raise HTTPException(status_code=400, detail="The default glossary cannot be deleted")
    retrieval = RetrievalService(db)
    for entry in repo.list_entries(ctx.tenant_id, glossary_id):
        try:
            retrieval.vector.delete_entry(str(entry.id), tenant_id=ctx.tenant_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Failed to delete entries from the vector index") from exc
    try:
        repo.delete_glossary(row)
    except IntegrityError as exc:
        _safe_rollback(db)
        raise HTTPException(
            status_code=409,
            detail="Glossary cannot be deleted because related entries still exist",
        ) from exc
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "delete", "glossary", glossary_id, {})
    return {"detail": "Deleted"}


@router.get("/{glossary_id}/entries", response_model=list[GlossaryEntryOut])
def list_entries(glossary_id: str, ctx: AuthContext = Depends(require_admin), db: Session = Depends(db_dep)):
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Glossary not found")
    return [_to_entry_schema(r) for r in repo.list_entries(ctx.tenant_id, glossary_id)]


@router.post("/{glossary_id}/entries", response_model=GlossaryEntryOut)
def create_entry(
    glossary_id: str,
    payload: GlossaryEntryCreate,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Glossary not found")

    try:
        row = _repo_create_entry(repo, ctx.tenant_id, glossary_id, ctx.user_id, payload.model_dump())
    except IntegrityError as exc:
        _safe_rollback(db)
        raise HTTPException(status_code=409, detail="Term already exists in this glossary") from exc

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
        _safe_rollback(db)
        try:
            retrieval.vector.delete_entry(str(row.id), tenant_id=ctx.tenant_id)
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="Failed to sync entry with the vector index") from exc
    _safe_commit(db)

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
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Glossary not found")
    row = repo.get_entry(ctx.tenant_id, glossary_id, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Glossary entry not found")

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
        raise HTTPException(status_code=502, detail="Failed to update entry embedding") from exc

    try:
        row = _repo_update_entry(repo, row, patch)
    except IntegrityError as exc:
        _safe_rollback(db)
        raise HTTPException(status_code=409, detail="Term already exists in this glossary") from exc
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
        _safe_rollback(db)
        raise HTTPException(status_code=502, detail="Failed to sync entry update with the vector index") from exc
    _safe_commit(db)

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
def delete_entry(
    glossary_id: str,
    entry_id: str,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = GlossaryRepository(db)
    row = repo.get_entry(ctx.tenant_id, glossary_id, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Glossary entry not found")
    retrieval = RetrievalService(db)
    _repo_delete_entry(repo, row)
    _safe_commit(db)
    try:
        retrieval.vector.delete_entry(entry_id, tenant_id=ctx.tenant_id)
    except Exception:
        logger.warning(
            "Failed to delete glossary vector entry tenant=%s entry_id=%s",
            ctx.tenant_id,
            entry_id,
        )
    AdminRepository(db).add_audit_log(ctx.tenant_id, ctx.user_id, "delete", "glossary_entry", entry_id, {})
    return {"detail": "Deleted"}


@router.post("/{glossary_id}/import-csv", response_model=GlossaryCsvImportResult)
async def import_entries_csv(
    glossary_id: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    repo = GlossaryRepository(db)
    glossary = repo.get_glossary(ctx.tenant_id, glossary_id)
    if not glossary:
        raise HTTPException(status_code=404, detail="Glossary not found")

    raw_bytes = await file.read()
    rows = _parse_csv_import(file.filename, raw_bytes)
    rows = _dedupe_import_rows_by_term(rows)
    retrieval = RetrievalService(db)
    provider = retrieval._provider_for_tenant(ctx.tenant_id)

    created = 0
    updated = 0
    created_ids: list[str] = []
    restored_vectors: list[tuple[str, list[float], dict]] = []

    try:
        existing_rows = [repo.find_entry_by_term(ctx.tenant_id, glossary_id, row.term) for row in rows]
        try:
            new_embeddings = await provider.embeddings([_entry_text(row.term, row.definition) for row in rows])
        except Exception as exc:
            logger.exception(
                "Glossary CSV import embeddings failed tenant=%s glossary_id=%s file=%s: %s",
                ctx.tenant_id,
                glossary_id,
                file.filename,
                str(exc)[:300],
            )
            raise HTTPException(status_code=502, detail="Failed to generate embeddings for glossary import") from exc
        if len(new_embeddings) != len(rows):
            logger.warning(
                "Glossary CSV import embedding count mismatch tenant=%s glossary_id=%s file=%s requested=%s received=%s",
                ctx.tenant_id,
                glossary_id,
                file.filename,
                len(rows),
                len(new_embeddings),
            )
            raise HTTPException(status_code=502, detail="Failed to generate embeddings for glossary import")

        old_rows = [row for row in existing_rows if row is not None]
        old_embeddings_map: dict[str, list[float]] = {}
        if old_rows:
            try:
                old_embeddings = await provider.embeddings([_entry_text(row.term, row.definition) for row in old_rows])
                if len(old_embeddings) == len(old_rows):
                    old_embeddings_map = {
                        str(row.id): vector for row, vector in zip(old_rows, old_embeddings, strict=False)
                    }
            except Exception:
                old_embeddings_map = {}

        for row, existing, embedding in zip(rows, existing_rows, new_embeddings, strict=False):
            old_payload = None
            if existing is not None:
                old_payload = {
                    "term": existing.term,
                    "definition": existing.definition,
                    "glossary_id": str(glossary.id),
                    "glossary_name": glossary.name,
                    "glossary_priority": glossary.priority,
                    "entry_priority": existing.priority,
                }

            if existing is None:
                try:
                    target = _repo_create_entry(repo, ctx.tenant_id, glossary_id, ctx.user_id, row.model_dump())
                except IntegrityError as exc:
                    raise HTTPException(status_code=409, detail="Term already exists in this glossary") from exc
                created += 1
                created_ids.append(str(target.id))
            else:
                try:
                    target = _repo_update_entry(repo, existing, row.model_dump())
                except IntegrityError as exc:
                    raise HTTPException(status_code=409, detail="Term already exists in this glossary") from exc
                updated += 1
                old_vector = old_embeddings_map.get(str(target.id))
                if old_vector is not None and old_payload is not None:
                    restored_vectors.append((str(target.id), old_vector, old_payload))

            retrieval.vector.upsert_entry(
                str(target.id),
                ctx.tenant_id,
                embedding,
                {
                    "term": target.term,
                    "definition": target.definition,
                    "glossary_id": str(glossary.id),
                    "glossary_name": glossary.name,
                    "glossary_priority": glossary.priority,
                    "entry_priority": target.priority,
                },
            )
    except HTTPException:
        _safe_rollback(db)
        for entry_id in created_ids:
            try:
                retrieval.vector.delete_entry(entry_id, tenant_id=ctx.tenant_id)
            except Exception:
                pass
        for entry_id, vector, payload in restored_vectors:
            try:
                retrieval.vector.upsert_entry(entry_id, ctx.tenant_id, vector, payload)
            except Exception:
                pass
        raise
    except Exception as exc:
        _safe_rollback(db)
        for entry_id in created_ids:
            try:
                retrieval.vector.delete_entry(entry_id, tenant_id=ctx.tenant_id)
            except Exception:
                pass
        for entry_id, vector, payload in restored_vectors:
            try:
                retrieval.vector.upsert_entry(entry_id, ctx.tenant_id, vector, payload)
            except Exception:
                pass
        logger.exception(
            "Glossary CSV import failed tenant=%s glossary_id=%s file=%s rows=%s",
            ctx.tenant_id,
            glossary_id,
            file.filename,
            len(rows),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to import CSV into glossary: {exc.__class__.__name__}",
        ) from exc

    _safe_commit(db)
    AdminRepository(db).add_audit_log(
        ctx.tenant_id,
        ctx.user_id,
        "import_csv",
        "glossary_entry",
        glossary_id,
        {"created": created, "updated": updated, "file_name": file.filename},
    )
    return GlossaryCsvImportResult(created=created, updated=updated)
