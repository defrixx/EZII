from fastapi import HTTPException, status
from sqlalchemy import select
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
        return
    row = User(id=ctx.user_id, tenant_id=ctx.tenant_id, email=ctx.email, role=ctx.role)
    db.add(row)
    db.commit()
