import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)
allowed_origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]

def startup_setup():
    try:
        # Keep startup non-blocking even when Qdrant is slow/unavailable.
        client = QdrantClient(url=settings.qdrant_url, timeout=2.0)
        collections = [c.name for c in client.get_collections().collections]
        if settings.qdrant_collection not in collections:
            client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(size=settings.embedding_vector_size, distance=Distance.COSINE),
            )
            return
        info = client.get_collection(settings.qdrant_collection)
        vectors = getattr(getattr(info, "config", None), "params", None)
        vectors_cfg = getattr(vectors, "vectors", None)
        existing_size = getattr(vectors_cfg, "size", None)
        if isinstance(existing_size, int) and existing_size != settings.embedding_vector_size:
            raise RuntimeError(
                f"Qdrant vector size mismatch: expected={settings.embedding_vector_size}, actual={existing_size}"
            )
    except Exception as exc:
        # App should still start if vector store is temporarily unavailable.
        logger.warning("Qdrant startup check failed: %s", str(exc)[:300])


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup_setup()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/health")
def api_health():
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
