from typing import List

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.models import Glossary, GlossaryEntry


class GlossaryRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_glossaries(self, tenant_id: str) -> List[Glossary]:
        stmt = (
            select(Glossary)
            .where(Glossary.tenant_id == tenant_id)
            .order_by(Glossary.priority.asc(), Glossary.created_at.asc())
        )
        return list(self.db.scalars(stmt))

    def list_enabled_glossaries(self, tenant_id: str) -> List[Glossary]:
        stmt = (
            select(Glossary)
            .where(Glossary.tenant_id == tenant_id, Glossary.enabled.is_(True))
            .order_by(Glossary.priority.asc(), Glossary.created_at.asc())
        )
        return list(self.db.scalars(stmt))

    def get_glossary(self, tenant_id: str, glossary_id: str) -> Glossary | None:
        stmt = select(Glossary).where(Glossary.id == glossary_id, Glossary.tenant_id == tenant_id)
        return self.db.scalar(stmt)

    def create_glossary(self, tenant_id: str, payload: dict) -> Glossary:
        row = Glossary(tenant_id=tenant_id, **payload)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_glossary(self, row: Glossary, payload: dict) -> Glossary:
        for k, v in payload.items():
            setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_glossary(self, row: Glossary) -> None:
        entries_stmt = select(GlossaryEntry).where(GlossaryEntry.glossary_id == row.id)
        for entry in self.db.scalars(entries_stmt):
            self.db.delete(entry)
        self.db.delete(row)
        self.db.commit()

    def list_entries(self, tenant_id: str, glossary_id: str) -> List[GlossaryEntry]:
        stmt = (
            select(GlossaryEntry)
            .where(GlossaryEntry.tenant_id == tenant_id, GlossaryEntry.glossary_id == glossary_id)
            .order_by(GlossaryEntry.priority.asc(), GlossaryEntry.created_at.asc())
        )
        return list(self.db.scalars(stmt))

    def get_entry(self, tenant_id: str, glossary_id: str, entry_id: str) -> GlossaryEntry | None:
        stmt = select(GlossaryEntry).where(
            GlossaryEntry.id == entry_id,
            GlossaryEntry.tenant_id == tenant_id,
            GlossaryEntry.glossary_id == glossary_id,
        )
        return self.db.scalar(stmt)

    def create_entry(self, tenant_id: str, glossary_id: str, created_by: str, payload: dict) -> GlossaryEntry:
        row = GlossaryEntry(tenant_id=tenant_id, glossary_id=glossary_id, created_by=created_by, **payload)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_entry(self, row: GlossaryEntry, payload: dict) -> GlossaryEntry:
        for k, v in payload.items():
            setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_entry(self, row: GlossaryEntry) -> None:
        self.db.delete(row)
        self.db.commit()

    def exact_match(self, tenant_id: str, normalized_query: str, glossary_ids: list[str]) -> List[dict]:
        if not glossary_ids:
            return []
        stmt = (
            select(
                GlossaryEntry.id,
                GlossaryEntry.term,
                GlossaryEntry.definition,
                GlossaryEntry.priority.label("entry_priority"),
                Glossary.id.label("glossary_id"),
                Glossary.priority.label("glossary_priority"),
                Glossary.name.label("glossary_name"),
            )
            .join(Glossary, Glossary.id == GlossaryEntry.glossary_id)
            .where(
                GlossaryEntry.tenant_id == tenant_id,
                GlossaryEntry.status == "active",
                GlossaryEntry.term.ilike(normalized_query),
                GlossaryEntry.glossary_id.in_(glossary_ids),
            )
        )
        rows = self.db.execute(stmt).all()
        return [
            {
                "id": str(r.id),
                "term": r.term,
                "definition": r.definition,
                "entry_priority": r.entry_priority,
                "glossary_id": str(r.glossary_id),
                "glossary_priority": r.glossary_priority,
                "glossary_name": r.glossary_name,
            }
            for r in rows
        ]

    def synonym_match(self, tenant_id: str, normalized_query: str, glossary_ids: list[str]) -> List[dict]:
        if not glossary_ids:
            return []
        stmt = (
            select(
                GlossaryEntry.id,
                GlossaryEntry.term,
                GlossaryEntry.definition,
                GlossaryEntry.priority.label("entry_priority"),
                Glossary.id.label("glossary_id"),
                Glossary.priority.label("glossary_priority"),
                Glossary.name.label("glossary_name"),
            )
            .join(Glossary, Glossary.id == GlossaryEntry.glossary_id)
            .where(
                GlossaryEntry.tenant_id == tenant_id,
                GlossaryEntry.status == "active",
                GlossaryEntry.glossary_id.in_(glossary_ids),
                or_(
                    GlossaryEntry.synonyms.any(normalized_query),
                    GlossaryEntry.synonyms.any(normalized_query.lower()),
                ),
            )
        )
        rows = self.db.execute(stmt).all()
        return [
            {
                "id": str(r.id),
                "term": r.term,
                "definition": r.definition,
                "entry_priority": r.entry_priority,
                "glossary_id": str(r.glossary_id),
                "glossary_priority": r.glossary_priority,
                "glossary_name": r.glossary_name,
            }
            for r in rows
        ]

    def default_glossary(self, tenant_id: str) -> Glossary | None:
        stmt = select(Glossary).where(Glossary.tenant_id == tenant_id, Glossary.is_default.is_(True))
        return self.db.scalar(stmt)
