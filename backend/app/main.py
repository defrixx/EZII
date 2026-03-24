import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import (
    http_exception_handler,
    request_id_from_request,
    unhandled_exception_handler,
    validation_exception_handler,
)

settings = get_settings()
logger = logging.getLogger(__name__)
allowed_origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response: Response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id_from_request(request))
        return response

def _ensure_qdrant_collection(client: QdrantClient, collection_name: str) -> None:
    collections = [c.name for c in client.get_collections().collections]
    if collection_name not in collections:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=settings.embedding_vector_size, distance=Distance.COSINE),
        )
        return
    info = client.get_collection(collection_name)
    vectors = getattr(getattr(info, "config", None), "params", None)
    vectors_cfg = getattr(vectors, "vectors", None)
    existing_size = getattr(vectors_cfg, "size", None)
    if isinstance(existing_size, int) and existing_size != settings.embedding_vector_size:
        raise RuntimeError(
            f"Qdrant vector size mismatch for {collection_name}: "
            f"expected={settings.embedding_vector_size}, actual={existing_size}"
        )


def startup_setup():
    try:
        # Keep startup non-blocking even when Qdrant is slow/unavailable.
        client = QdrantClient(url=settings.qdrant_url, timeout=2.0)
        _ensure_qdrant_collection(client, settings.qdrant_collection)
        _ensure_qdrant_collection(client, settings.qdrant_documents_collection)
    except Exception as exc:
        # App should still start if vector store is temporarily unavailable.
        logger.warning("Qdrant startup check failed: %s", str(exc)[:300])


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_setup()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/health")
def api_health():
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
