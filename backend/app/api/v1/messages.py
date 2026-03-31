from dataclasses import dataclass, field
import json
import re
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import auth_dep, ensure_user_exists
from app.api.v1.auth import enforce_csrf_for_cookie_auth
from app.core.markdown_security import normalize_markdown_text, render_markdown_to_safe_html, sanitize_markdown_stream_chunk
from app.core.message_limits import format_limit_reset_at_utc, limit_window_reset_at_utc, limit_window_start_utc
from app.core.logging_utils import redact_pii, safe_payload, sanitize_text_for_logs
from app.core.rate_limit import check_rate_limit
from app.core.security import AuthContext
from app.db.session import SessionLocal
from app.repositories.admin_repository import AdminRepository
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import MessageCreate
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/messages", tags=["messages"])

DEFAULT_CHAT_CONTEXT_ENABLED = True
DEFAULT_HISTORY_USER_TURNS = 6
DEFAULT_HISTORY_MESSAGES = 12
DEFAULT_HISTORY_TOKEN_BUDGET = 1200
DEFAULT_REWRITE_HISTORY_MESSAGES = 8
CONFIDENCE_LINE_RE = re.compile(r"(?im)^\s*confidence level\s*:\s*(low|medium|high)\s*$")


def _fallback_answer() -> str:
    return (
        "I could not find enough precise information in the current glossary to answer confidently.\n"
        "Try rephrasing the question and include a specific term, practice, or school."
    )


def _clarifying_fallback_answer() -> str:
    return (
        "I could not find a relevant match in the knowledge base for this request.\n"
        "Please clarify what you need: a term, document, policy, team, process, or external source."
    )


def _source_types(intent: str, has_web: bool, has_documents: bool, has_glossary: bool) -> list[str]:
    source_types: list[str] = []
    if has_glossary:
        source_types.append("glossary")
    if has_documents:
        source_types.append("upload")
    if intent == "composite":
        source_types.append("synthesis")
    if has_web:
        source_types.append("website")
    return source_types


def _retrieval_payload(res: dict, source_types: list[str]) -> dict[str, Any]:
    return {
        "answer_mode": res.get("answer_mode", "grounded"),
        "fallback_reason": res.get("fallback_reason"),
        "retrieval_degraded": bool(res.get("retrieval_degraded", False)),
        "retrieval_warnings": list(res.get("retrieval_warnings") or []),
        "source_types": source_types,
        "document_ids": res.get("document_ids", []),
        "document_titles": res.get("document_titles", []),
        "web_snapshot_ids": res.get("web_snapshot_ids", []),
        "ranking_scores": res.get("ranking_scores", {}),
        "rewritten_query": res.get("rewritten_query"),
        "rewrite_used": res.get("rewrite_used", False),
        "history_messages_used": res.get("history_messages_used", 0),
        "history_token_estimate": res.get("history_token_estimate", 0),
        "history_trimmed": res.get("history_trimmed", False),
    }


def _sse_data(data: str) -> str:
    # Keep exact newline structure for Markdown-sensitive streaming chunks.
    # split("\n") preserves empty/trailing segments, unlike splitlines().
    lines = str(data).split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


def _sse_event(event: str, data: str) -> str:
    return f"event: {event}\n{_sse_data(data)}"


async def _stream_answer_with_compat(
    retrieval: RetrievalService,
    *,
    provider,
    query: str,
    context: str,
    conversation_history: list[dict[str, str]],
    knowledge_mode: str,
    strict_glossary_mode: bool,
    response_tone: str,
    intent: str,
    answer_mode: str,
    requested_items: int | None,
) -> AsyncIterator[dict[str, Any]]:
    kwargs = {
        "provider": provider,
        "query": query,
        "context": context,
        "conversation_history": conversation_history,
        "knowledge_mode": knowledge_mode,
        "strict_glossary_mode": strict_glossary_mode,
        "response_tone": response_tone,
        "intent": intent,
        "answer_mode": answer_mode,
    }
    if requested_items is not None:
        kwargs["requested_items"] = requested_items
    try:
        stream = retrieval.stream_answer(**kwargs)
    except TypeError:
        kwargs.pop("requested_items", None)
        stream = retrieval.stream_answer(**kwargs)
    async for event in stream:
        yield event if isinstance(event, dict) else {"type": "content", "content": str(event)}


@dataclass
class PreparedMessageContext:
    knowledge_mode: str
    empty_retrieval_mode: str
    strict_glossary_mode: bool
    show_confidence: bool
    response_tone: str
    chat_context_enabled: bool = DEFAULT_CHAT_CONTEXT_ENABLED
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    rewrite_history: list[dict[str, str]] = field(default_factory=list)
    history_messages_used: int = 0
    history_token_estimate: int = 0
    history_trimmed: bool = False


@dataclass
class StreamingMetrics:
    retrieval_latency_ms: float = 0.0
    rewrite_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    stream_chunks: int = 0
    provider_usage: dict[str, Any] | None = None
    rewrite_usage: dict[str, Any] | None = None
    fallback_reason: str | None = None
    answer_mode: str = "grounded"


def _estimate_token_count(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _truncate_to_token_budget(content: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    char_budget = max(16, token_budget * 4)
    if len(content) <= char_budget:
        return content
    return f"{content[: max(0, char_budget - 3)].rstrip()}..."


def _build_conversation_history(
    messages: list[Any],
    current_message_id: str,
    user_turn_limit: int,
    message_limit: int,
    token_budget: int,
) -> tuple[list[dict[str, str]], int, bool]:
    eligible = [
        message
        for message in messages
        if str(getattr(message, "id", "")) != current_message_id and getattr(message, "role", "") in {"user", "assistant"}
    ]
    selected: list[dict[str, str]] = []
    token_estimate = 0
    user_turns = 0
    remaining_budget = token_budget
    trimmed = False

    total_eligible = len(eligible)
    selected_count = 0

    for message in reversed(eligible):
        role = str(message.role)
        if role == "user" and user_turns >= user_turn_limit:
            trimmed = True
            break
        content = str(message.content or "").strip()
        if not content:
            continue

        estimated_tokens = _estimate_token_count(content)
        content_for_prompt = content
        if estimated_tokens > remaining_budget:
            content_for_prompt = _truncate_to_token_budget(content, remaining_budget)
            estimated_tokens = _estimate_token_count(content_for_prompt)
            trimmed = True
        if not content_for_prompt or estimated_tokens > remaining_budget:
            trimmed = True
            break

        selected.append({"role": role, "content": content_for_prompt})
        token_estimate += estimated_tokens
        remaining_budget -= estimated_tokens
        if role == "user":
            user_turns += 1
        selected_count += 1
        if len(selected) >= message_limit:
            trimmed = selected_count < total_eligible
            break

    selected.reverse()
    if len(selected) < len(eligible):
        trimmed = True
    return selected, token_estimate, trimmed


def _persist_error_trace_sync(
    tenant_id: str,
    user_id: str,
    chat_id: str,
    payload_content: str,
    exc: Exception,
    metadata: dict[str, Any] | None = None,
) -> None:
    sanitized_message = redact_pii(str(exc))
    error_metadata = {"query": sanitize_text_for_logs(payload_content, max_len=800)}
    if metadata:
        error_metadata.update(metadata)
    with SessionLocal() as db:
        a_repo = AdminRepository(db)
        a_repo.add_error_log(
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            error_type="provider_or_retrieval_error",
            message=sanitized_message,
            metadata=safe_payload(error_metadata),
        )
        a_repo.add_trace(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "model": "unknown",
                "knowledge_mode": metadata.get("knowledge_mode", "glossary_documents") if metadata else "glossary_documents",
                "answer_mode": "error",
                "source_types": [],
                "glossary_entries_used": [],
                "document_ids": [],
                "web_snapshot_ids": [],
                "web_domains_used": [],
                "ranking_scores": {},
                "latency_ms": 0,
                "token_usage": safe_payload(error_metadata),
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
    window_start = limit_window_start_utc()
    if hasattr(c_repo, "count_user_messages_since"):
        used = c_repo.count_user_messages_since(ctx.tenant_id, ctx.user_id, window_start)
    else:
        used = c_repo.count_user_messages(ctx.tenant_id, ctx.user_id)
    if used >= max_messages:
        reset_at = format_limit_reset_at_utc(limit_window_reset_at_utc(window_start))
        raise HTTPException(
            status_code=403,
            detail=f"Message limit reached ({max_messages}). Limit will reset on {reset_at}.",
        )


def _prepare_message_request_sync(ctx: AuthContext, chat_id: str, payload: MessageCreate) -> PreparedMessageContext:
    with SessionLocal() as db:
        ensure_user_exists(db, ctx)
        c_repo = ChatRepository(db)
        a_repo = AdminRepository(db)

        chat = c_repo.get_chat(ctx.tenant_id, ctx.user_id, chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        if bool(getattr(chat, "is_archived", False)):
            raise HTTPException(status_code=409, detail="Chat is archived. Unarchive it before sending new messages.")

        provider_settings = a_repo.get_provider(ctx.tenant_id)
        max_user_messages = provider_settings.max_user_messages_total if provider_settings is not None else 5
        user_message = None
        if payload.is_retry:
            user_message = c_repo.find_recent_user_message(
                ctx.tenant_id,
                chat_id,
                ctx.user_id,
                payload.content,
                within_seconds=180,
            )
            # Retry can reuse a recent identical user message only while it still has
            # no assistant reply; otherwise treat as a new turn to preserve limits.
            if user_message is not None and c_repo.has_assistant_reply_after(
                ctx.tenant_id,
                chat_id,
                after_created_at=user_message.created_at,
            ):
                user_message = None
        if user_message is None:
            _enforce_user_message_limit(ctx, c_repo, provider_settings)
        if user_message is None:
            user_message = c_repo.add_message(ctx.tenant_id, chat_id, ctx.user_id, "user", payload.content)
        chat_context_enabled = (
            provider_settings.chat_context_enabled
            if provider_settings is not None
            else DEFAULT_CHAT_CONTEXT_ENABLED
        )
        conversation_history: list[dict[str, str]] = []
        rewrite_history: list[dict[str, str]] = []
        history_token_estimate = 0
        history_trimmed = False
        if chat_context_enabled:
            history_user_turn_limit = max(
                1,
                min(
                    max_user_messages,
                    provider_settings.history_user_turn_limit if provider_settings is not None else DEFAULT_HISTORY_USER_TURNS,
                ),
            )
            history_message_limit = (
                provider_settings.history_message_limit if provider_settings is not None else DEFAULT_HISTORY_MESSAGES
            )
            history_token_budget = (
                provider_settings.history_token_budget if provider_settings is not None else DEFAULT_HISTORY_TOKEN_BUDGET
            )
            rewrite_history_message_limit = (
                provider_settings.rewrite_history_message_limit
                if provider_settings is not None
                else DEFAULT_REWRITE_HISTORY_MESSAGES
            )
            recent_messages = c_repo.list_recent_messages(
                ctx.tenant_id,
                chat_id,
                limit=max(history_message_limit + 1, (history_user_turn_limit * 2) + 1),
            )
            conversation_history, history_token_estimate, history_trimmed = _build_conversation_history(
                recent_messages,
                str(user_message.id),
                history_user_turn_limit,
                history_message_limit,
                history_token_budget,
            )
            rewrite_history = conversation_history[-rewrite_history_message_limit:]
        return PreparedMessageContext(
            knowledge_mode=provider_settings.knowledge_mode if provider_settings else "glossary_documents",
            empty_retrieval_mode=(
                provider_settings.empty_retrieval_mode
                if provider_settings is not None
                else "model_only_fallback"
            ),
            strict_glossary_mode=(
                provider_settings.strict_glossary_mode
                if provider_settings is not None
                else bool(payload.strict_glossary_mode)
            ),
            show_confidence=provider_settings.show_confidence if provider_settings else False,
            response_tone=provider_settings.response_tone if provider_settings else "consultative_supportive",
            chat_context_enabled=chat_context_enabled,
            conversation_history=conversation_history,
            rewrite_history=rewrite_history,
            history_messages_used=len(conversation_history),
            history_token_estimate=history_token_estimate,
            history_trimmed=history_trimmed,
        )


def _persist_assistant_result_sync(
    ctx: AuthContext,
    chat_id: str,
    answer: str,
    source_types: list[str],
    res: dict,
    metrics: StreamingMetrics,
    prep: PreparedMessageContext,
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
                "knowledge_mode": res.get("knowledge_mode", "glossary_documents"),
                "answer_mode": metrics.answer_mode,
                "source_types": source_types,
                "glossary_entries_used": [x["id"] for x in res["top_glossary"]],
                "document_ids": res.get("document_ids", []),
                "web_snapshot_ids": res.get("web_snapshot_ids", []),
                "web_domains_used": res["web_domains_used"],
                "ranking_scores": res.get("ranking_scores", {}),
                "latency_ms": metrics.total_latency_ms,
                "token_usage": {
                    "provider_usage": metrics.provider_usage or {},
                    "rewrite_usage": metrics.rewrite_usage or {},
                    "retrieval_latency_ms": round(metrics.retrieval_latency_ms, 2),
                    "rewrite_latency_ms": round(metrics.rewrite_latency_ms, 2),
                    "generation_latency_ms": round(metrics.generation_latency_ms, 2),
                    "stream_chunks": metrics.stream_chunks,
                    "fallback_reason": metrics.fallback_reason,
                    "answer_mode": metrics.answer_mode,
                    "rewritten_query": res.get("rewritten_query"),
                    "rewrite_used": res.get("rewrite_used", False),
                    "chat_context_enabled": prep.chat_context_enabled,
                    "history_messages_used": res.get("history_messages_used", 0),
                    "history_token_estimate": res.get("history_token_estimate", 0),
                    "history_trimmed": res.get("history_trimmed", False),
                },
                "status": "fallback" if metrics.fallback_reason else "ok",
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
    enforce_csrf_for_cookie_auth(request)
    check_rate_limit(request, ctx.tenant_id, ctx.user_id)
    prep = await run_in_threadpool(_prepare_message_request_sync, ctx, chat_id, payload)

    async def event_gen():
        retrieval = RetrievalService()
        request_started_at = time.perf_counter()
        metrics = StreamingMetrics()

        try:
            rewritten_query = payload.content
            rewrite_history = prep.rewrite_history or prep.conversation_history
            if rewrite_history:
                rewrite_fn = getattr(retrieval, "rewrite_query", None)
                if callable(rewrite_fn):
                    rewritten_query, rewrite_usage, rewrite_latency_ms = await rewrite_fn(
                        ctx.tenant_id,
                        payload.content,
                        rewrite_history,
                    )
                    metrics.rewrite_usage = rewrite_usage if isinstance(rewrite_usage, dict) else None
                    metrics.rewrite_latency_ms = rewrite_latency_ms
            retrieval_started_at = time.perf_counter()
            res = await retrieval.run(
                ctx.tenant_id,
                rewritten_query,
                prep.knowledge_mode,
                prep.strict_glossary_mode,
            )
            metrics.retrieval_latency_ms = (time.perf_counter() - retrieval_started_at) * 1000
            res["rewritten_query"] = rewritten_query
            res["rewrite_used"] = rewritten_query.strip() != payload.content.strip()
            res["history_messages_used"] = prep.history_messages_used
            res["history_token_estimate"] = prep.history_token_estimate
            res["history_trimmed"] = prep.history_trimmed
            source_types = list(res.get("source_types") or _source_types(
                intent=res["intent"],
                has_web=bool(res["web_domains_used"]),
                has_documents=bool(res.get("top_documents")),
                has_glossary=bool(res["top_glossary"]),
            ))

            if not res["top_glossary"] and not res.get("top_documents") and not res.get("top_websites") and not res["web_domains_used"]:
                metrics.fallback_reason = "no_retrieval_context"
                if prep.empty_retrieval_mode == "strict_fallback":
                    metrics.answer_mode = "strict_fallback"
                    res["answer_mode"] = "strict_fallback"
                    res["fallback_reason"] = metrics.fallback_reason
                    answer = _fallback_answer()
                    yield _sse_data(answer)
                elif prep.empty_retrieval_mode == "clarifying_fallback":
                    metrics.answer_mode = "clarifying"
                    res["answer_mode"] = "clarifying"
                    res["fallback_reason"] = metrics.fallback_reason
                    answer = _clarifying_fallback_answer()
                    yield _sse_data(answer)
                else:
                    metrics.answer_mode = "model_only"
                    res["answer_mode"] = "model_only"
                    res["fallback_reason"] = metrics.fallback_reason
                    source_types = ["model"]
                    chunks: list[str] = []
                    generation_started_at = time.perf_counter()
                    async for event in _stream_answer_with_compat(
                        retrieval,
                        provider=res["provider"],
                        query=payload.content,
                        context="",
                        conversation_history=prep.conversation_history,
                        knowledge_mode=prep.knowledge_mode,
                        strict_glossary_mode=prep.strict_glossary_mode,
                        response_tone=prep.response_tone,
                        intent="no_retrieval_context",
                        answer_mode="model_only",
                        requested_items=res.get("requested_items"),
                    ):
                        if event.get("type") == "usage":
                            usage = event.get("usage")
                            if isinstance(usage, dict):
                                metrics.provider_usage = usage
                            continue
                        chunk = sanitize_markdown_stream_chunk(str(event.get("content") or ""))
                        if not chunk:
                            continue
                        metrics.stream_chunks += 1
                        chunks.append(chunk)
                        yield _sse_data(chunk)
                    answer = "".join(chunks).strip() or _clarifying_fallback_answer()
                    metrics.generation_latency_ms = (time.perf_counter() - generation_started_at) * 1000
            else:
                metrics.answer_mode = "grounded"
                res["answer_mode"] = "grounded"
                res["fallback_reason"] = None
                chunks: list[str] = []
                generation_started_at = time.perf_counter()
                async for event in _stream_answer_with_compat(
                    retrieval,
                    provider=res["provider"],
                    query=payload.content,
                    context=res["assembled_context"],
                    conversation_history=prep.conversation_history,
                    knowledge_mode=prep.knowledge_mode,
                    strict_glossary_mode=prep.strict_glossary_mode,
                    response_tone=prep.response_tone,
                    intent=res["intent"],
                    answer_mode="grounded",
                    requested_items=res.get("requested_items"),
                ):
                    if event.get("type") == "usage":
                        usage = event.get("usage")
                        if isinstance(usage, dict):
                            metrics.provider_usage = usage
                        continue
                    chunk = sanitize_markdown_stream_chunk(str(event.get("content") or ""))
                    if not chunk:
                        continue
                    metrics.stream_chunks += 1
                    chunks.append(chunk)
                    yield _sse_data(chunk)

                answer = "".join(chunks).strip() or "No response"
                metrics.generation_latency_ms = (time.perf_counter() - generation_started_at) * 1000
                if not chunks:
                    metrics.fallback_reason = "empty_provider_response"
                if prep.show_confidence:
                    # Avoid duplicated confidence lines when the model already included one.
                    if not CONFIDENCE_LINE_RE.search(answer):
                        confidence_suffix = f"\n\nConfidence level: {res['confidence']}"
                        answer = f"{answer}{confidence_suffix}"
                        yield _sse_data(confidence_suffix)
            answer = normalize_markdown_text(answer)
            trusted_html = render_markdown_to_safe_html(answer)
            metrics.total_latency_ms = (time.perf_counter() - request_started_at) * 1000
            retrieval_payload = _retrieval_payload(res, source_types)

            trace_id = await run_in_threadpool(
                _persist_assistant_result_sync,
                ctx,
                chat_id,
                answer,
                source_types,
                res,
                metrics,
                prep,
            )

            yield _sse_event("sources", json.dumps(source_types, ensure_ascii=False))
            yield _sse_event("retrieval", json.dumps(retrieval_payload, ensure_ascii=False))
            yield _sse_event("trace", trace_id)
            yield _sse_event("trusted_html", trusted_html)
            yield _sse_data("[DONE]")
        except Exception as exc:
            if isinstance(exc, HTTPException):
                await run_in_threadpool(
                    _persist_error_trace_sync,
                    ctx.tenant_id,
                    ctx.user_id,
                    chat_id,
                    payload.content,
                    exc,
                    {
                        "stream_chunks": metrics.stream_chunks,
                        "retrieval_latency_ms": round(metrics.retrieval_latency_ms, 2),
                        "generation_latency_ms": round(metrics.generation_latency_ms, 2),
                        "fallback_reason": metrics.fallback_reason,
                        "knowledge_mode": prep.knowledge_mode,
                        "http_status": exc.status_code,
                    },
                )
                yield _sse_event("error", str(exc.detail))
                yield _sse_data("[DONE]")
                return
            await run_in_threadpool(
                _persist_error_trace_sync,
                ctx.tenant_id,
                ctx.user_id,
                chat_id,
                payload.content,
                exc,
                {
                    "stream_chunks": metrics.stream_chunks,
                    "retrieval_latency_ms": round(metrics.retrieval_latency_ms, 2),
                    "generation_latency_ms": round(metrics.generation_latency_ms, 2),
                    "fallback_reason": metrics.fallback_reason,
                    "knowledge_mode": prep.knowledge_mode,
                },
            )
            yield _sse_event("error", f"Request processing failed: {redact_pii(str(exc))}")
            yield _sse_data("[DONE]")

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
