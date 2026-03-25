import logging
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def request_id_from_request(request: Request) -> str:
    request_id = getattr(request.state, "request_id", "")
    return str(request_id or uuid.uuid4())


def error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    detail: Any = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "detail": message,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        },
    }
    if detail is not None:
        body["error"]["detail"] = detail
    response = JSONResponse(status_code=status_code, content=body)
    response.headers["X-Request-ID"] = request_id
    return response


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = request_id_from_request(request)
    message = str(exc.detail) if isinstance(exc.detail, str) else "Request failed"
    return error_response(
        request_id=request_id,
        status_code=exc.status_code,
        code="http_error",
        message=message,
        detail=None if isinstance(exc.detail, str) else exc.detail,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = request_id_from_request(request)
    return error_response(
        request_id=request_id,
        status_code=422,
        code="validation_error",
        message="Invalid input data",
        detail=exc.errors(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = request_id_from_request(request)
    logger.exception("Unhandled application error request_id=%s", request_id)
    return error_response(
        request_id=request_id,
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )
