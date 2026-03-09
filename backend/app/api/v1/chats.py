from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.api.deps import auth_dep, db_dep, ensure_user_exists
from app.core.rate_limit import check_rate_limit
from app.core.security import AuthContext
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import ChatCreate, ChatDetail, ChatOut, ChatUpdate, MessageOut

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[ChatOut])
def list_chats(
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    rows = repo.list_chats(ctx.tenant_id, ctx.user_id)
    return [
        ChatOut(id=str(r.id), title=r.title, created_at=r.created_at, updated_at=r.updated_at)
        for r in rows
    ]


@router.post("", response_model=ChatOut)
def create_chat(
    payload: ChatCreate,
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    r = repo.create_chat(ctx.tenant_id, ctx.user_id, payload.title)
    return ChatOut(id=str(r.id), title=r.title, created_at=r.created_at, updated_at=r.updated_at)


@router.get("/{chat_id}", response_model=ChatDetail)
def get_chat(chat_id: str, ctx: AuthContext = Depends(auth_dep), db: Session = Depends(db_dep)):
    ensure_user_exists(db, ctx)
    repo = ChatRepository(db)
    c = repo.get_chat(ctx.tenant_id, ctx.user_id, chat_id)
    if not c:
        raise HTTPException(status_code=404, detail="Чат не найден")
    msgs = repo.list_messages(ctx.tenant_id, chat_id)
    return ChatDetail(
        chat=ChatOut(id=str(c.id), title=c.title, created_at=c.created_at, updated_at=c.updated_at),
        messages=[
            MessageOut(
                id=str(m.id),
                role=m.role,
                content=m.content,
                source_types=m.source_types or [],
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )


@router.patch("/{chat_id}", response_model=ChatOut)
def update_chat(
    chat_id: str,
    payload: ChatUpdate,
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    chat = repo.update_chat_title(ctx.tenant_id, ctx.user_id, chat_id, payload.title)
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return ChatOut(id=str(chat.id), title=chat.title, created_at=chat.created_at, updated_at=chat.updated_at)


@router.delete("/{chat_id}", status_code=204)
def delete_chat(
    chat_id: str,
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
    db: Session = Depends(db_dep),
):
    ensure_user_exists(db, ctx)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    repo = ChatRepository(db)
    deleted = repo.delete_chat(ctx.tenant_id, ctx.user_id, chat_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return Response(status_code=204)
