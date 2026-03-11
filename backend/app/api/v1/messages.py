from dataclasses import dataclass
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import auth_dep, ensure_user_exists
from app.core.logging_utils import redact_pii, safe_payload
from app.core.rate_limit import check_rate_limit
from app.core.security import AuthContext
from app.db.session import SessionLocal
from app.repositories.admin_repository import AdminRepository
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import MessageCreate
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/messages", tags=["messages"])


def _fallback_answer() -> str:
    return (
        "Я не нашел достаточно точных данных в текущем глоссарии для уверенного ответа.\n"
        "Попробуйте переформулировать вопрос: укажите конкретный термин, практику или школу."
    )


def _source_types(intent: str, has_web: bool) -> list[str]:
    source_types = ["glossary"]
    if intent == "composite":
        source_types.append("synthesis")
    if has_web:
        source_types.append("web")
    source_types.append("model")
    return source_types


@dataclass
class PreparedMessageContext:
    strict_glossary_mode: bool
    web_enabled: bool
    show_confidence: bool
    response_tone: str


def _persist_error_trace_sync(
    tenant_id: str,
    user_id: str,
    chat_id: str,
    payload_content: str,
    exc: Exception,
) -> None:
    sanitized_message = redact_pii(str(exc))
    with SessionLocal() as db:
        a_repo = AdminRepository(db)
        a_repo.add_error_log(
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            error_type="provider_or_retrieval_error",
            message=sanitized_message,
            metadata=safe_payload({"query": payload_content}),
        )
        a_repo.add_trace(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "model": "unknown",
                "glossary_entries_used": [],
                "web_domains_used": [],
                "ranking_scores": {},
                "latency_ms": 0,
                "token_usage": {},
                "status": "error",
            }
        )


def _enforce_user_message_limit(
    ctx: AuthContext,
    c_repo: ChatRepository,
    provider_settings,
) -> None:
    if ctx.role == "admin":
        return
    max_messages = provider_settings.max_user_messages_total if provider_settings is not None else 5
    used = c_repo.count_user_messages(ctx.tenant_id, ctx.user_id)
    if used >= max_messages:
        raise HTTPException(
            status_code=403,
            detail=f"Достигнут лимит сообщений ({max_messages}). Обратитесь к администратору.",
        )


def _prepare_message_request_sync(ctx: AuthContext, chat_id: str, payload: MessageCreate) -> PreparedMessageContext:
    with SessionLocal() as db:
        ensure_user_exists(db, ctx)
        c_repo = ChatRepository(db)
        a_repo = AdminRepository(db)

        chat = c_repo.get_chat(ctx.tenant_id, ctx.user_id, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Чат не найден")

        provider_settings = a_repo.get_provider(ctx.tenant_id)
        _enforce_user_message_limit(ctx, c_repo, provider_settings)
        c_repo.add_message(ctx.tenant_id, chat_id, ctx.user_id, "user", payload.content)
        return PreparedMessageContext(
            strict_glossary_mode=(
                provider_settings.strict_glossary_mode
                if provider_settings is not None
                else bool(payload.strict_glossary_mode)
            ),
            web_enabled=(
                provider_settings.web_enabled
                if provider_settings is not None
                else bool(payload.web_enabled)
            ),
            show_confidence=provider_settings.show_confidence if provider_settings else False,
            response_tone=provider_settings.response_tone if provider_settings else "consultative_supportive",
        )


def _persist_assistant_result_sync(
    ctx: AuthContext,
    chat_id: str,
    answer: str,
    source_types: list[str],
    res: dict,
    latency_ms: float,
    usage: dict,
) -> str:
    with SessionLocal() as db:
        c_repo = ChatRepository(db)
        a_repo = AdminRepository(db)
        c_repo.add_message(
            ctx.tenant_id,
            chat_id,
            ctx.user_id,
            "assistant",
            answer,
            source_types=source_types,
        )
        trace = a_repo.add_trace(
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "chat_id": chat_id,
                "model": res["provider"].model,
                "glossary_entries_used": [x["id"] for x in res["top_glossary"]],
                "web_domains_used": res["web_domains_used"],
                "ranking_scores": {x["id"]: x["score"] for x in res["top_glossary"]},
                "latency_ms": latency_ms,
                "token_usage": usage,
                "status": "ok",
            }
        )
        return str(trace.id)


@router.post("/{chat_id}/stream")
async def send_message_stream(
    chat_id: str,
    payload: MessageCreate,
    request: Request,
    ctx: AuthContext = Depends(auth_dep),
):
    async def event_gen():
        check_rate_limit(request, ctx.tenant_id, ctx.user_id)
        retrieval = RetrievalService()

        try:
            prep = await run_in_threadpool(_prepare_message_request_sync, ctx, chat_id, payload)
            res = await retrieval.run(
                ctx.tenant_id,
                payload.content,
                prep.strict_glossary_mode,
                prep.web_enabled,
            )
            source_types = _source_types(intent=res["intent"], has_web=bool(res["web_domains_used"]))

            if not res["top_glossary"] and not res["web_domains_used"]:
                answer = _fallback_answer()
                yield f"data: {answer}\n\n"
                latency_ms = 0
                usage = {}
            else:
                chunks: list[str] = []
                async for chunk in retrieval.stream_answer(
                    provider=res["provider"],
                    query=payload.content,
                    context=res["assembled_context"],
                    strict_glossary_mode=prep.strict_glossary_mode,
                    response_tone=prep.response_tone,
                    intent=res["intent"],
                ):
                    chunks.append(chunk)
                    yield f"data: {chunk}\n\n"

                answer = "".join(chunks).strip() or "Нет ответа"
                if prep.show_confidence:
                    confidence_suffix = f"\n\nУровень уверенности: {res['confidence']}"
                    answer = f"{answer}{confidence_suffix}"
                    yield f"data: {confidence_suffix}\n\n"
                usage = {}
                latency_ms = 0

            trace_id = await run_in_threadpool(
                _persist_assistant_result_sync,
                ctx,
                chat_id,
                answer,
                source_types,
                res,
                latency_ms,
                usage,
            )

            yield f"event: sources\ndata: {json.dumps(source_types, ensure_ascii=False)}\n\n"
            yield f"event: trace\ndata: {trace_id}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            if isinstance(exc, HTTPException):
                yield f"event: error\ndata: {exc.detail}\n\n"
                yield "data: [DONE]\n\n"
                return
            await run_in_threadpool(
                _persist_error_trace_sync,
                ctx.tenant_id,
                ctx.user_id,
                chat_id,
                payload.content,
                exc,
            )
            yield f"event: error\ndata: Ошибка обработки запроса: {redact_pii(str(exc))}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
