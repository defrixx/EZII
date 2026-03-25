from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import Depends
from sqlalchemy.orm import Session
from app.core.security import AuthContext, get_auth_context
from app.db.session import get_db
from app.models import User


def db_dep(db: Session = Depends(get_db)) -> Session:
    return db


def auth_dep(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    return ctx


def ensure_user_exists(db: Session, ctx: AuthContext) -> None:
    stmt = select(User).where(User.id == ctx.user_id)
    existing = db.scalar(stmt)
    if existing:
        if str(existing.tenant_id) != ctx.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User tenant mismatch")
        updated = False
        if ctx.email and existing.email != ctx.email:
            existing.email = ctx.email
            updated = True
        if existing.role != ctx.role:
            existing.role = ctx.role
            updated = True
        if updated:
            db.commit()
        return

    safe_email = (ctx.email or "").strip() or f"{ctx.user_id}@keycloak.local"
    existing_by_email = db.scalar(select(User).where(User.tenant_id == ctx.tenant_id, User.email == safe_email))
    if existing_by_email:
        if str(existing_by_email.id) != str(ctx.user_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User identity conflict for tenant/email",
            )
        if existing_by_email.role != ctx.role:
            existing_by_email.role = ctx.role
            db.commit()
        return

    row = User(id=ctx.user_id, tenant_id=ctx.tenant_id, email=safe_email, role=ctx.role)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conflict = db.scalar(select(User).where(User.tenant_id == ctx.tenant_id, User.email == safe_email))
        if conflict:
            if str(conflict.id) != str(ctx.user_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User identity conflict for tenant/email",
                )
            if conflict.role != ctx.role:
                conflict.role = ctx.role
                db.commit()
            return
        raise
