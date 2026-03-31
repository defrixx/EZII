from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from app.api.deps import auth_dep, db_dep, ensure_user_exists
from app.api.v1.auth import enforce_csrf_for_cookie_auth
from app.core.markdown_security import render_markdown_to_safe_html
from app.core.rate_limit import check_rate_limit
from app.core.security import AuthContext
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import ChatCreate, ChatDetail, ChatOut, ChatUpdate, MessageOut

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[ChatOut])
def list_chats(
    request: Request,
    include_archived: bool = Query(default=False),
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    rows = repo.list_chats(ctx.tenant_id, ctx.user_id, include_archived=include_archived)
    return [
        ChatOut(
            id=str(r.id),
            title=r.title,
            is_pinned=bool(getattr(r, "is_pinned", False)),
            is_archived=bool(getattr(r, "is_archived", False)),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("", response_model=ChatOut)
def create_chat(
    payload: ChatCreate,
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    r = repo.create_chat(ctx.tenant_id, ctx.user_id, payload.title)
    return ChatOut(
        id=str(r.id),
        title=r.title,
        is_pinned=bool(getattr(r, "is_pinned", False)),
        is_archived=bool(getattr(r, "is_archived", False)),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


@router.get("/{chat_id}", response_model=ChatDetail)
def get_chat(chat_id: UUID, ctx: AuthContext = Depends(auth_dep), db: Session = Depends(db_dep)):
    ensure_user_exists(db, ctx)
    repo = ChatRepository(db)
    chat_id_str = str(chat_id)
    c = repo.get_chat(ctx.tenant_id, ctx.user_id, chat_id_str)
    if not c:
        raise HTTPException(status_code=404, detail="Chat not found")
    msgs = repo.list_messages(ctx.tenant_id, chat_id_str)
    return ChatDetail(
        chat=ChatOut(
            id=str(c.id),
            title=c.title,
            is_pinned=bool(getattr(c, "is_pinned", False)),
            is_archived=bool(getattr(c, "is_archived", False)),
            created_at=c.created_at,
            updated_at=c.updated_at,
        ),
        messages=[
            MessageOut(
                id=str(m.id),
                role=m.role,
                content=m.content,
                trusted_html=(render_markdown_to_safe_html(m.content) if m.role == "assistant" else None),
                source_types=m.source_types or [],
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )


@router.patch("/{chat_id}", response_model=ChatOut)
def update_chat(
    chat_id: UUID,
    payload: ChatUpdate,
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    if payload.title is None and payload.is_pinned is None and payload.is_archived is None:
        raise HTTPException(status_code=400, detail="No fields to update")
    chat = repo.update_chat(
        ctx.tenant_id,
        ctx.user_id,
        str(chat_id),
        title=payload.title,
        is_pinned=payload.is_pinned,
        is_archived=payload.is_archived,
    )
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return ChatOut(
        id=str(chat.id),
        title=chat.title,
        is_pinned=bool(getattr(chat, "is_pinned", False)),
        is_archived=bool(getattr(chat, "is_archived", False)),
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


@router.delete("/{chat_id}", status_code=204)
def delete_chat(
    chat_id: UUID,
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    enforce_csrf_for_cookie_auth(request)
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    deleted = repo.delete_chat(ctx.tenant_id, ctx.user_id, str(chat_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat not found")
    return Response(status_code=204)
