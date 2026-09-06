import uuid
import logging
import re
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from qdrant_client import QdrantClient
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from app.api.v1.router import router
from app.core.config import get_settings
from app.core.errors import http_exception_handler, request_id_from_request, unhandled_exception_handler, validation_exception_handler
from app.db.session import SessionLocal
from app.services.ingestion_service import recover_interrupted_uploads
from app.services.cleanup_service import process_cleanup_tasks

settings=get_settings()
logger=logging.getLogger("ezii.requests")
LOCAL_HOSTS={"127.0.0.1","localhost","::1","backend","testserver"}

def local_hostname(value:str)->bool:
    try:
        return (urlsplit(value if "://" in value else f"//{value}").hostname or "").lower() in LOCAL_HOSTS
    except ValueError:
        return False

@asynccontextmanager
async def lifespan(_:FastAPI):
    with SessionLocal() as db: recover_interrupted_uploads(db);process_cleanup_tasks(db)
    yield
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request:Request,call_next):
        request.state.request_id=str(uuid.uuid4());started=time.perf_counter()
        if not local_hostname(request.headers.get("host","")):
            response=JSONResponse({"detail":"local_access_only"},status_code=400)
        elif request.method not in {"GET","HEAD","OPTIONS"} and (
            request.headers.get("sec-fetch-site","").lower()=="cross-site"
            or (request.headers.get("origin") and not local_hostname(request.headers["origin"]))
        ):
            response=JSONResponse({"detail":"cross_site_request_blocked"},status_code=403)
        else:
            response=await call_next(request)
        response.headers["X-Request-ID"]=request_id_from_request(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
        match=re.search(r"/knowledge-bases/([0-9a-f-]{36})",request.url.path);logger.info("request_complete request_id=%s method=%s path=%s status=%s latency_ms=%.1f knowledge_base_id=%s",request.state.request_id,request.method,request.url.path,response.status_code,(time.perf_counter()-started)*1000,match.group(1) if match else "-");return response
app=FastAPI(title=settings.app_name,version="1.0.0",lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
app.add_exception_handler(HTTPException,http_exception_handler); app.add_exception_handler(RequestValidationError,validation_exception_handler); app.add_exception_handler(Exception,unhandled_exception_handler)
@app.get("/health")
@app.get("/api/v1/health")
def health(): return {"status":"ok"}
@app.get("/ready")
@app.get("/api/v1/ready")
def ready():
    checks={"postgres":False,"qdrant":False}
    try:
        with SessionLocal() as db: db.execute(text("SELECT 1")); checks["postgres"]=True
    except Exception: pass
    try: QdrantClient(url=settings.qdrant_url,timeout=2).get_collections(); checks["qdrant"]=True
    except Exception: pass
    ok=all(checks.values()); return JSONResponse({"status":"ok" if ok else "degraded","checks":checks},status_code=200 if ok else 503)
app.include_router(router,prefix="/api/v1")
