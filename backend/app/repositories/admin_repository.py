from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import AllowlistDomain, AuditLog, ErrorLog, ProviderSetting, ResponseTrace


class AdminRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_allowlist(self, tenant_id: str) -> list[AllowlistDomain]:
        stmt = select(AllowlistDomain).where(AllowlistDomain.tenant_id == tenant_id).order_by(AllowlistDomain.domain.asc())
        return list(self.db.scalars(stmt))

    def create_allowlist(self, tenant_id: str, domain: str, notes: str | None, enabled: bool) -> AllowlistDomain:
        row = AllowlistDomain(tenant_id=tenant_id, domain=domain, notes=notes, enabled=enabled)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_allowlist(
        self,
        tenant_id: str,
        domain_id: str,
        domain: str | None = None,
        notes: str | None = None,
        enabled: bool | None = None,
    ) -> AllowlistDomain | None:
        row = self.db.scalar(
            select(AllowlistDomain).where(AllowlistDomain.id == domain_id, AllowlistDomain.tenant_id == tenant_id)
        )
        if not row:
            return None
        if domain is not None:
            row.domain = domain
        if notes is not None:
            row.notes = notes
        if enabled is not None:
            row.enabled = enabled
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_allowlist(self, tenant_id: str, domain_id: str) -> bool:
        row = self.db.scalar(
            select(AllowlistDomain).where(AllowlistDomain.id == domain_id, AllowlistDomain.tenant_id == tenant_id)
        )
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def get_provider(self, tenant_id: str) -> ProviderSetting | None:
        stmt = select(ProviderSetting).where(ProviderSetting.tenant_id == tenant_id)
        return self.db.scalar(stmt)

    def upsert_provider(self, tenant_id: str, payload: dict) -> ProviderSetting:
        row = self.get_provider(tenant_id)
        if row:
            for k, v in payload.items():
                setattr(row, k, v)
        else:
            row = ProviderSetting(tenant_id=tenant_id, **payload)
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def add_audit_log(self, tenant_id: str, user_id: str, action: str, entity_type: str, entity_id: str, payload: dict):
        row = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        self.db.add(row)
        self.db.commit()

    def add_error_log(self, tenant_id: str, user_id: str | None, chat_id: str | None, error_type: str, message: str, metadata: dict):
        row = ErrorLog(
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            error_type=error_type,
            message=message,
            metadata_json=metadata,
        )
        self.db.add(row)
        self.db.commit()

    def add_trace(self, payload: dict) -> ResponseTrace:
        row = ResponseTrace(**payload)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_error_logs(self, tenant_id: str, limit: int = 100) -> list[ErrorLog]:
        stmt = select(ErrorLog).where(ErrorLog.tenant_id == tenant_id).order_by(ErrorLog.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def list_traces(self, tenant_id: str, limit: int = 100) -> list[ResponseTrace]:
        stmt = (
            select(ResponseTrace)
            .where(ResponseTrace.tenant_id == tenant_id)
            .order_by(ResponseTrace.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
