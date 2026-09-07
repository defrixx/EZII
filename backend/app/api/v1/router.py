import hashlib, ipaddress, json, logging, re, socket, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import Chat, Document, DocumentChunk, Glossary, GlossaryEntry, IngestionJob, KnowledgeBase, Message, ModelConnection, ModelEndpoint, ResponseTrace, StorageCleanupTask
from app.core.config import get_settings
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.services.provider_service import OpenAIProvider, validate_base_url
from app.services.playbook_sync_service import PlaybookSyncService
from app.services.ingestion_service import add_text_chunks, finish_upload_job
from app.services.cleanup_service import process_cleanup_tasks, safe_unlink
from app.services.vector_service import VectorService
from app.services.retrieval_service import hybrid_rank, query_terms

router=APIRouter(); settings=get_settings();logger=logging.getLogger(__name__)
def db_dep(): yield from get_db()
def lexical_terms(value:str)->list[str]: return query_terms(value)
class ORM(BaseModel): model_config=ConfigDict(from_attributes=True)
class KBIn(BaseModel):
    name:str=Field(min_length=1,max_length=255); description:str|None=None; system_prompt:str|None=Field(None,max_length=12000); publication_mode:Literal["manual","automatic"]="manual"; knowledge_mode:list[Literal["upload","website_snapshot","github_playbook"]]=Field(default_factory=lambda:["upload","website_snapshot","github_playbook"]); empty_retrieval_mode:Literal["strict_fallback","model_only_fallback","clarifying_fallback"]="clarifying_fallback"; response_tone:str="neutral"; chat_context_enabled:bool=True; history_message_limit:int=Field(12,ge=0,le=100); history_token_budget:int=Field(1200,ge=0,le=100000); context_token_budget:int=Field(4000,ge=256,le=200000); chunk_size_chars:int=Field(900,ge=200,le=8000); chunk_overlap_chars:int=Field(250,ge=0,le=4000); chat_model_id:uuid.UUID|None=None; embedding_model_id:uuid.UUID|None=None; is_default:bool=False
class KBPatch(BaseModel):
    name:str|None=Field(None,min_length=1,max_length=255); description:str|None=None; system_prompt:str|None=Field(None,max_length=12000); publication_mode:str|None=None; knowledge_mode:list[str]|None=None; empty_retrieval_mode:str|None=None; response_tone:str|None=None; chat_context_enabled:bool|None=None; history_message_limit:int|None=Field(None,ge=0,le=100); history_token_budget:int|None=Field(None,ge=0,le=100000); context_token_budget:int|None=Field(None,ge=256,le=200000); chunk_size_chars:int|None=Field(None,ge=200,le=8000); chunk_overlap_chars:int|None=Field(None,ge=0,le=4000); chat_model_id:uuid.UUID|None=None; embedding_model_id:uuid.UUID|None=None; is_default:bool|None=None
class KBOut(KBIn,ORM): id:uuid.UUID; reindex_required:bool; created_at:datetime; updated_at:datetime
class ConnectionIn(BaseModel):
    name:str=Field(min_length=1,max_length=255); kind:Literal["openrouter","lm_studio","openai_compatible"]; base_url:str; api_key:str|None=None; clear_api_key:bool=False; timeout_s:int=Field(30,ge=1,le=120); retry_count:int=Field(2,ge=0,le=5); enabled:bool=True
class ConnectionOut(ORM):
    id:uuid.UUID; name:str; kind:str; base_url:str; has_api_key:bool; timeout_s:int; retry_count:int; enabled:bool
class ModelIn(BaseModel):
    connection_id:uuid.UUID; name:str=Field(min_length=1,max_length=255); model_id:str=Field(min_length=1,max_length=255); capability:Literal["chat","embedding"]; vector_size:int|None=Field(None,ge=1,le=100000); enabled:bool=True
    @model_validator(mode="after")
    def valid_capability(self):
        if self.capability not in {"chat","embedding"} or (self.capability=="embedding" and not self.vector_size): raise ValueError("invalid_model_capability")
        return self
class ModelOut(ModelIn,ORM): id:uuid.UUID
class ModelPatch(BaseModel): name:str|None=None; model_id:str|None=None; vector_size:int|None=None; enabled:bool|None=None
class ModelProbeIn(BaseModel): connection_id:uuid.UUID; model_id:str=Field(min_length=1,max_length=255); capability:Literal["chat","embedding"]
class ChatIn(BaseModel): title:str="New chat"; knowledge_base_id:uuid.UUID
class ChatPatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    title:str|None=None; is_pinned:bool|None=None; is_archived:bool|None=None
class ChatOut(ORM): id:uuid.UUID; knowledge_base_id:uuid.UUID; title:str; is_pinned:bool; is_archived:bool; created_at:datetime; updated_at:datetime
class MessageIn(BaseModel): content:str=Field(min_length=1,max_length=10000); locale:Literal["ru","en"]="ru"
class SiteIn(BaseModel): url:str; title:str|None=None
class BulkSourceAction(BaseModel): source_ids:list[uuid.UUID]=Field(min_length=1,max_length=500); action:Literal["approve","archive","enable","disable"]
class QualityCheckIn(BaseModel): questions:list[str]=Field(min_length=1,max_length=50)
class GlossaryIn(BaseModel): name:str=Field(min_length=1,max_length=255); description:str|None=None; priority:int=Field(100,ge=0,le=10000); enabled:bool=True; is_default:bool=False
class TermIn(BaseModel): term:str=Field(min_length=1,max_length=255); definition:str=Field(min_length=1); synonyms:list[str]=Field(default_factory=list); example:str|None=None; forbidden_interpretations:list[str]=Field(default_factory=list); priority:int=Field(100,ge=0,le=10000); status:Literal["active","disabled"]="active"
class MessageOut(ORM): id:uuid.UUID; role:str; content:str; source_types:list[str]|None=[]; metadata_json:dict; created_at:datetime

def require_kb(db,id):
    row=db.get(KnowledgeBase,id)
    if not row: raise HTTPException(404,"knowledge_base_not_found")
    return row
def validate_kb_models(db:Session,chat_model_id,embedding_model_id):
    for model_id,capability in ((chat_model_id,"chat"),(embedding_model_id,"embedding")):
        if model_id:
            model=db.get(ModelEndpoint,model_id)
            if not model or model.capability!=capability or not model.enabled:
                raise HTTPException(422,f"invalid_{capability}_model")
def validate_kb_settings(values:dict):
    modes=values.get("knowledge_mode")
    if modes is not None and (not modes or not set(modes)<={"upload","website_snapshot","github_playbook"}): raise HTTPException(422,"invalid_knowledge_mode")
    empty_mode=values.get("empty_retrieval_mode")
    if empty_mode is not None and empty_mode not in {"strict_fallback","model_only_fallback","clarifying_fallback"}: raise HTTPException(422,"invalid_empty_retrieval_mode")
    if "system_prompt" in values and values["system_prompt"] is not None:
        values["system_prompt"]=values["system_prompt"].strip() or None
    size=values.get("chunk_size_chars");overlap=values.get("chunk_overlap_chars")
    if size is not None and overlap is not None and overlap>=size: raise HTTPException(422,"invalid_chunk_overlap")
def build_system_prompt(kb:KnowledgeBase,context:str):
    custom=f"KNOWLEDGE BASE INSTRUCTIONS:\n{kb.system_prompt.strip()}\n\n" if kb.system_prompt and kb.system_prompt.strip() else ""
    return custom+f"APPLICATION RULES:\nAnswer only from the supplied knowledge context. Cite uncertainty clearly. Response tone: {kb.response_tone}.\nCONTEXT:\n{context}"
def connection_out(row): return ConnectionOut(id=row.id,name=row.name,kind=row.kind,base_url=row.base_url,has_api_key=bool(row.api_key),timeout_s=row.timeout_s,retry_count=row.retry_count,enabled=row.enabled)
def provider_for_connection(conn:ModelConnection|None):
    if not conn or not conn.enabled: raise HTTPException(409,"model_connection_unavailable")
    try: validate_base_url(conn.kind,conn.base_url,set(settings.local_model_hosts.split(",")))
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    return OpenAIProvider(conn.base_url,decrypt_secret(conn.api_key) if conn.api_key else None,conn.timeout_s,conn.retry_count,conn.kind,set(settings.local_model_hosts.split(",")))
def provider_for(model:ModelEndpoint,db:Session): return provider_for_connection(db.get(ModelConnection,model.connection_id))
def commit_or_conflict(db:Session,code:str="duplicate_resource"):
    try: db.commit()
    except IntegrityError as exc:
        db.rollback();raise HTTPException(409,code) from exc

@router.get("/knowledge-bases",response_model=list[KBOut])
def list_kb(db:Session=Depends(db_dep)): return list(db.scalars(select(KnowledgeBase).order_by(KnowledgeBase.name)))
@router.get("/knowledge-bases/{id}",response_model=KBOut)
def get_kb(id:uuid.UUID,db:Session=Depends(db_dep)): return require_kb(db,id)
@router.post("/knowledge-bases",response_model=KBOut,status_code=201)
def create_kb(p:KBIn,db:Session=Depends(db_dep)):
    if p.publication_mode not in {"manual","automatic"}: raise HTTPException(422,"invalid_publication_mode")
    validate_kb_models(db,p.chat_model_id,p.embedding_model_id)
    values=p.model_dump();validate_kb_settings(values)
    if p.is_default:
        for x in db.scalars(select(KnowledgeBase).where(KnowledgeBase.is_default.is_(True))): x.is_default=False
    row=KnowledgeBase(**values); db.add(row); commit_or_conflict(db,"knowledge_base_name_exists"); db.refresh(row); return row
@router.patch("/knowledge-bases/{id}",response_model=KBOut)
def update_kb(id:uuid.UUID,p:KBPatch,db:Session=Depends(db_dep)):
    row=require_kb(db,id); old=row.embedding_model_id
    changes=p.model_dump(exclude_unset=True)
    effective_size=changes.get("chunk_size_chars",row.chunk_size_chars);effective_overlap=changes.get("chunk_overlap_chars",row.chunk_overlap_chars)
    if effective_overlap>=effective_size: raise HTTPException(422,"invalid_chunk_overlap")
    if changes.get("publication_mode") not in {None,"manual","automatic"}: raise HTTPException(422,"invalid_publication_mode")
    validate_kb_models(db,changes.get("chat_model_id"),changes.get("embedding_model_id"))
    validate_kb_settings(changes)
    if changes.get("is_default"):
        for x in db.scalars(select(KnowledgeBase).where(KnowledgeBase.is_default.is_(True),KnowledgeBase.id!=id)): x.is_default=False
    for k,v in changes.items(): setattr(row,k,v)
    if old!=row.embedding_model_id or any(key in changes for key in ("chunk_size_chars","chunk_overlap_chars")): row.reindex_required=True
    row.updated_at=datetime.now(timezone.utc); commit_or_conflict(db,"knowledge_base_name_exists"); db.refresh(row); return row
@router.get("/knowledge-bases/{id}/index-status")
def index_status(id:uuid.UUID,db:Session=Depends(db_dep)):
    kb=require_kb(db,id)
    sources_count=db.scalar(select(func.count(Document.id)).where(Document.knowledge_base_id==id)) or 0
    chunks_count=db.scalar(select(func.count(DocumentChunk.id)).join(Document).where(Document.knowledge_base_id==id)) or 0
    indexed_count=db.scalar(select(func.count(DocumentChunk.id)).join(Document).where(Document.knowledge_base_id==id,DocumentChunk.embedding_model_id==kb.embedding_model_id)) if kb.embedding_model_id else 0
    return {"knowledge_base_id":str(id),"reindex_required":kb.reindex_required,"sources_count":sources_count,"chunks_count":chunks_count,"indexed_chunks_count":indexed_count or 0}
@router.delete("/knowledge-bases/{id}",status_code=204)
def delete_kb(id:uuid.UUID,confirm:bool=False,db:Session=Depends(db_dep)):
    if not confirm: raise HTTPException(409,"confirmation_required")
    row=require_kb(db,id)
    for source_id in list(db.scalars(select(Document.id).where(Document.knowledge_base_id==id))): delete_source(id,source_id,db)
    db.delete(row); db.commit()

@router.get("/settings/connections",response_model=list[ConnectionOut])
def connections(db:Session=Depends(db_dep)): return [connection_out(x) for x in db.scalars(select(ModelConnection).order_by(ModelConnection.name))]
@router.get("/settings/connections/{id}",response_model=ConnectionOut)
def get_connection(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(ModelConnection,id)
    if not row: raise HTTPException(404,"connection_not_found")
    return connection_out(row)
@router.post("/settings/connections",response_model=ConnectionOut,status_code=201)
def create_connection(p:ConnectionIn,db:Session=Depends(db_dep)):
    try: url=validate_base_url(p.kind,p.base_url,set(settings.local_model_hosts.split(",")))
    except ValueError as e: raise HTTPException(422,str(e))
    if p.kind!="lm_studio" and not p.api_key: raise HTTPException(422,"api_key_required")
    row=ModelConnection(name=p.name,kind=p.kind,base_url=url,api_key=encrypt_secret(p.api_key) if p.api_key else None,timeout_s=p.timeout_s,retry_count=p.retry_count,enabled=p.enabled); db.add(row); commit_or_conflict(db,"connection_name_exists"); db.refresh(row); return connection_out(row)
@router.post("/settings/connections/test")
async def test_unsaved_connection(p:ConnectionIn):
    if p.kind!="lm_studio" and not p.api_key: raise HTTPException(422,"api_key_required")
    try:
        provider=OpenAIProvider(p.base_url,p.api_key,p.timeout_s,p.retry_count,p.kind,set(settings.local_model_hosts.split(",")))
        models=await provider.models()
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    except Exception as exc: raise HTTPException(502,"provider_unavailable") from exc
    return {"ok":True,"models":[str(item.get("id")) for item in models if item.get("id")]}
@router.put("/settings/connections/{id}",response_model=ConnectionOut)
def update_connection(id:uuid.UUID,p:ConnectionIn,db:Session=Depends(db_dep)):
    row=db.get(ModelConnection,id)
    if not row: raise HTTPException(404,"connection_not_found")
    try: row.base_url=validate_base_url(p.kind,p.base_url,set(settings.local_model_hosts.split(",")))
    except ValueError as e: raise HTTPException(422,str(e))
    for k in ("name","kind","timeout_s","retry_count","enabled"): setattr(row,k,getattr(p,k))
    if p.clear_api_key: row.api_key=None
    elif p.api_key: row.api_key=encrypt_secret(p.api_key)
    if p.kind!="lm_studio" and not row.api_key: raise HTTPException(422,"api_key_required")
    row.updated_at=datetime.now(timezone.utc)
    commit_or_conflict(db,"connection_name_exists"); db.refresh(row); return connection_out(row)
@router.delete("/settings/connections/{id}",status_code=204)
def delete_connection(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(ModelConnection,id)
    if not row: raise HTTPException(404,"connection_not_found")
    used=db.scalar(select(KnowledgeBase.id).join(ModelEndpoint,((KnowledgeBase.chat_model_id==ModelEndpoint.id)|(KnowledgeBase.embedding_model_id==ModelEndpoint.id))).where(ModelEndpoint.connection_id==id).limit(1))
    if used: raise HTTPException(409,"connection_in_use")
    for endpoint in db.scalars(select(ModelEndpoint).where(ModelEndpoint.connection_id==id,ModelEndpoint.capability=="embedding")):
        try: VectorService().delete_model_collection(endpoint.id)
        except Exception as exc: raise HTTPException(503,"vector_cleanup_failed") from exc
    db.delete(row);db.commit()
@router.post("/settings/connections/{id}/test")
async def test_connection(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(ModelConnection,id)
    if not row: raise HTTPException(404,"connection_not_found")
    provider=OpenAIProvider(row.base_url,decrypt_secret(row.api_key) if row.api_key else None,row.timeout_s,row.retry_count,row.kind,set(settings.local_model_hosts.split(",")))
    try: models=await provider.models()
    except Exception as e: raise HTTPException(502,"provider_unavailable") from e
    endpoints=list(db.scalars(select(ModelEndpoint).where(ModelEndpoint.connection_id==id,ModelEndpoint.enabled.is_(True))));chat=next((x for x in endpoints if x.capability=="chat"),None);embedding=next((x for x in endpoints if x.capability=="embedding"),None);chat_available=None;embeddings_available=None;embedding_dimension=None;warnings=[]
    if chat:
        try: chat_available=await provider.probe_chat(chat.model_id)
        except Exception: chat_available=False;warnings.append("chat_probe_failed")
    if embedding:
        try: vector=(await provider.embeddings(embedding.model_id,["dimension probe"]))[0];embedding_dimension=len(vector);embeddings_available=embedding_dimension==embedding.vector_size
        except Exception: embeddings_available=False;warnings.append("embedding_probe_failed")
    return {"ok":True,"models":[str(x.get("id")) for x in models if x.get("id")],"chat_available":chat_available,"embeddings_available":embeddings_available,"embedding_dimension":embedding_dimension,"warning_codes":warnings}
@router.get("/settings/connections/{id}/models")
async def discover_models(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(ModelConnection,id)
    if not row: raise HTTPException(404,"connection_not_found")
    try: models=await OpenAIProvider(row.base_url,decrypt_secret(row.api_key) if row.api_key else None,row.timeout_s,row.retry_count,row.kind,set(settings.local_model_hosts.split(","))).models()
    except Exception as exc: raise HTTPException(502,"provider_unavailable") from exc
    return {"models":[{"id":str(item.get("id"))} for item in models if item.get("id")]}
@router.get("/settings/models",response_model=list[ModelOut])
def models(db:Session=Depends(db_dep)): return list(db.scalars(select(ModelEndpoint).order_by(ModelEndpoint.name)))
@router.get("/diagnostics/traces")
def traces(knowledge_base_id:uuid.UUID|None=None,db:Session=Depends(db_dep)):
    query=select(ResponseTrace).order_by(ResponseTrace.created_at.desc()).limit(100)
    if knowledge_base_id: query=query.where(ResponseTrace.knowledge_base_id==knowledge_base_id)
    return list(db.scalars(query))
@router.get("/knowledge-bases/{kb_id}/statistics")
def knowledge_statistics(kb_id:uuid.UUID,db:Session=Depends(db_dep)):
    require_kb(db,kb_id);traces=list(db.scalars(select(ResponseTrace).where(ResponseTrace.knowledge_base_id==kb_id).order_by(ResponseTrace.created_at.desc()).limit(1000)))
    sources=list(db.scalars(select(Document).where(Document.knowledge_base_id==kb_id)));source_names={str(source.id):source.title for source in sources};uses:dict[str,int]={}
    for trace in traces:
        for source_id in trace.source_ids: uses[source_id]=uses.get(source_id,0)+1
    grounded=sum(trace.answer_mode=="grounded" for trace in traces);no_results=sum(not trace.source_ids for trace in traces)
    return {"queries":len(traces),"grounded":grounded,"model_only":len(traces)-grounded,"no_results":no_results,"average_latency_ms":round(sum(trace.latency_ms for trace in traces)/len(traces),1) if traces else 0,"sources":len(sources),"chunks":db.scalar(select(func.count(DocumentChunk.id)).join(Document).where(Document.knowledge_base_id==kb_id)) or 0,"top_sources":[{"id":source_id,"title":source_names.get(source_id,"—"),"uses":count} for source_id,count in sorted(uses.items(),key=lambda item:-item[1])[:10]],"recent_no_result_queries":[trace.ranking_scores.get("query","") for trace in traces if not trace.source_ids][:10]}
@router.get("/knowledge-bases/{kb_id}/operations")
def knowledge_operations(kb_id:uuid.UUID,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id);jobs=list(db.scalars(select(IngestionJob).where(IngestionJob.knowledge_base_id==kb_id).order_by(IngestionJob.created_at.desc()).limit(20)));total=db.scalar(select(func.count(DocumentChunk.id)).join(Document).where(Document.knowledge_base_id==kb_id)) or 0;indexed=db.scalar(select(func.count(DocumentChunk.id)).join(Document).where(Document.knowledge_base_id==kb_id,DocumentChunk.embedding_model_id==kb.embedding_model_id)) if kb.embedding_model_id else 0
    return {"jobs":[{"id":str(job.id),"kind":job.kind,"status":job.status,"attempts":job.attempts,"error_code":job.error_code,"updated_at":job.updated_at} for job in jobs],"index":{"total":total,"indexed":indexed or 0,"required":kb.reindex_required}}
@router.post("/knowledge-bases/{kb_id}/quality/check")
def quality_check(kb_id:uuid.UUID,p:QualityCheckIn,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id);chunks=list(db.scalars(select(DocumentChunk).join(Document).where(Document.knowledge_base_id==kb.id,Document.source_type.in_(kb.knowledge_mode),Document.status=="approved",Document.enabled_in_retrieval.is_(True))));results=[]
    for raw in p.questions:
        question=raw.strip()
        if not question: continue
        ranked=hybrid_rank(question,chunks,None,limit=5);source_ids=list(dict.fromkeys(str(item.chunk.document_id) for item in ranked));results.append({"question":question,"matched_chunks":len(ranked),"source_ids":source_ids,"top_score":ranked[0].score if ranked else 0})
    covered=sum(bool(result["matched_chunks"]) for result in results)
    return {"questions":len(results),"covered":covered,"coverage_percent":round(covered*100/len(results),1) if results else 0,"results":results}
@router.get("/maintenance/status")
def maintenance_status(db:Session=Depends(db_dep)):
    return {"knowledge_bases":db.scalar(select(func.count(KnowledgeBase.id))) or 0,"sources":db.scalar(select(func.count(Document.id))) or 0,"chats":db.scalar(select(func.count(Chat.id))) or 0,"pending_ingestion_jobs":db.scalar(select(func.count(IngestionJob.id)).where(IngestionJob.status.in_(["queued","processing"]))) or 0,"pending_cleanup_tasks":db.scalar(select(func.count(StorageCleanupTask.id)).where(StorageCleanupTask.status=="pending")) or 0}
@router.post("/maintenance/retry-cleanup")
def retry_cleanup(confirm:bool=False,db:Session=Depends(db_dep)):
    if not confirm: raise HTTPException(409,"confirmation_required")
    return process_cleanup_tasks(db)
@router.post("/settings/models",response_model=ModelOut,status_code=201)
def create_model(p:ModelIn,db:Session=Depends(db_dep)):
    if p.capability not in {"chat","embedding"} or (p.capability=="embedding" and not p.vector_size): raise HTTPException(422,"invalid_model_capability")
    if not db.get(ModelConnection,p.connection_id): raise HTTPException(404,"connection_not_found")
    row=ModelEndpoint(**p.model_dump()); db.add(row); commit_or_conflict(db,"model_endpoint_exists"); db.refresh(row); return row
@router.post("/settings/models/probe")
async def probe_model(p:ModelProbeIn,db:Session=Depends(db_dep)):
    provider=provider_for_connection(db.get(ModelConnection,p.connection_id));started=time.perf_counter()
    try:
        if p.capability=="chat": return {"ok":await provider.probe_chat(p.model_id),"capability":"chat","latency_ms":round((time.perf_counter()-started)*1000,1)}
        vector=(await provider.embeddings(p.model_id,["EZII model connection test"]))[0]
        return {"ok":True,"capability":"embedding","dimension":len(vector),"latency_ms":round((time.perf_counter()-started)*1000,1)}
    except Exception as exc: raise HTTPException(502,"model_probe_failed") from exc
@router.patch("/settings/models/{id}",response_model=ModelOut)
def update_model(id:uuid.UUID,p:ModelPatch,db:Session=Depends(db_dep)):
    row=db.get(ModelEndpoint,id)
    if not row: raise HTTPException(404,"model_not_found")
    changes=p.model_dump(exclude_unset=True);embedding_changed=row.capability=="embedding" and any(key in changes and changes[key]!=getattr(row,key) for key in ("model_id","vector_size"))
    for key,value in changes.items(): setattr(row,key,value)
    if row.capability=="embedding" and not row.vector_size: raise HTTPException(422,"invalid_model_capability")
    if embedding_changed:
        for kb in db.scalars(select(KnowledgeBase).where(KnowledgeBase.embedding_model_id==row.id)): kb.reindex_required=True
    row.updated_at=datetime.now(timezone.utc);db.commit();db.refresh(row);return row
@router.post("/settings/models/{id}/test")
async def test_model(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(ModelEndpoint,id)
    if not row: raise HTTPException(404,"model_not_found")
    if not row.enabled: raise HTTPException(409,"model_disabled")
    provider=provider_for(row,db);started=time.perf_counter()
    try:
        if row.capability=="chat":
            if not await provider.probe_chat(row.model_id): raise RuntimeError("empty_chat_response")
            return {"ok":True,"capability":"chat","latency_ms":round((time.perf_counter()-started)*1000,1)}
        vector=(await provider.embeddings(row.model_id,["EZII model connection test"]))[0]
        dimension=len(vector)
        return {"ok":dimension==row.vector_size,"capability":"embedding","dimension":dimension,"expected_dimension":row.vector_size,"latency_ms":round((time.perf_counter()-started)*1000,1)}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(502,"model_probe_failed") from exc
@router.delete("/settings/models/{id}",status_code=204)
def delete_model(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(ModelEndpoint,id)
    if not row: raise HTTPException(404,"model_not_found")
    if db.scalar(select(KnowledgeBase.id).where((KnowledgeBase.chat_model_id==id)|(KnowledgeBase.embedding_model_id==id)).limit(1)): raise HTTPException(409,"model_in_use")
    if row.capability=="embedding":
        try: VectorService().delete_model_collection(row.id)
        except Exception as exc: raise HTTPException(503,"vector_cleanup_failed") from exc
    db.delete(row);db.commit()

@router.get("/chats",response_model=list[ChatOut])
def chats(db:Session=Depends(db_dep)): return list(db.scalars(select(Chat).order_by(Chat.updated_at.desc())))
@router.post("/chats",response_model=ChatOut,status_code=201)
def create_chat(p:ChatIn,db:Session=Depends(db_dep)):
    require_kb(db,p.knowledge_base_id); row=Chat(**p.model_dump()); db.add(row); db.commit(); db.refresh(row); return row
@router.patch("/chats/{id}",response_model=ChatOut)
def patch_chat(id:uuid.UUID,p:ChatPatch,db:Session=Depends(db_dep)):
    row=db.get(Chat,id)
    if not row: raise HTTPException(404,"chat_not_found")
    for k,v in p.model_dump(exclude_none=True).items(): setattr(row,k,v)
    row.updated_at=datetime.now(timezone.utc); db.commit(); db.refresh(row); return row
@router.get("/chats/{id}")
def chat(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(Chat,id)
    if not row: raise HTTPException(404,"chat_not_found")
    msgs=list(db.scalars(select(Message).where(Message.chat_id==id).order_by(Message.created_at)))
    return {"chat":ChatOut.model_validate(row),"messages":[MessageOut.model_validate(x) for x in msgs]}
@router.delete("/chats/{id}",status_code=204)
def delete_chat(id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.get(Chat,id)
    if not row: raise HTTPException(404,"chat_not_found")
    db.delete(row); db.commit()

@router.post("/knowledge-bases/{kb_id}/sources/upload",status_code=201)
async def upload_source(kb_id:uuid.UUID,file:UploadFile=File(...),title:str|None=Form(None),db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id)
    if "upload" not in kb.knowledge_mode: raise HTTPException(409,"source_type_disabled")
    data=await file.read(settings.document_upload_max_bytes+1)
    if len(data)>settings.document_upload_max_bytes: raise HTTPException(413,"file_too_large")
    suffix=Path(file.filename or "document.txt").suffix.lower()
    if suffix not in {".txt",".md",".pdf"}: raise HTTPException(415,"unsupported_file_type")
    if suffix in {".txt",".md"} and b"\x00" in data: raise HTTPException(415,"invalid_text_signature")
    safe_name=Path(file.filename or "document.txt").name
    if suffix==".pdf" and not data.startswith(b"%PDF-"): raise HTTPException(415,"invalid_pdf_signature")
    checksum=hashlib.sha256(data).hexdigest();existing=db.scalar(select(Document).where(Document.knowledge_base_id==kb.id,Document.source_type=="upload",Document.checksum==checksum,Document.file_name==safe_name,Document.status!="archived").limit(1))
    if existing:
        existing_job=db.scalar(select(IngestionJob).where(IngestionJob.document_id==existing.id).order_by(IngestionJob.created_at.desc()).limit(1));return {"id":str(existing.id),"status":existing.status,"title":existing.title,"job_id":str(existing_job.id) if existing_job else None,"deduplicated":True}
    row=Document(knowledge_base_id=kb.id,title=title or safe_name,source_type="upload",mime_type=file.content_type,file_name=safe_name,status="processing",checksum=checksum,metadata_json={"publication_mode":kb.publication_mode})
    db.add(row);db.flush();storage=Path(settings.document_storage_path)/str(kb.id)/str(row.id)/safe_name;storage.parent.mkdir(parents=True,exist_ok=True);storage.write_bytes(data);row.storage_path=str(storage)
    job=IngestionJob(knowledge_base_id=kb.id,document_id=row.id,kind="upload",status="processing");db.add(job);db.commit()
    try: finish_upload_job(db,row,job);kb=db.get(KnowledgeBase,kb.id);kb.reindex_required=bool(kb.embedding_model_id);db.commit()
    except ValueError as exc:
        db.rollback();row=db.get(Document,row.id);job=db.get(IngestionJob,job.id);row.status="failed";job.status="failed";job.error_code=str(exc);db.commit();raise HTTPException(422,str(exc)) from exc
    db.refresh(row);return {"id":str(row.id),"status":row.status,"title":row.title,"job_id":str(job.id)}
@router.get("/knowledge-bases/{kb_id}/sources")
def sources(kb_id:uuid.UUID,db:Session=Depends(db_dep)): require_kb(db,kb_id); return list(db.scalars(select(Document).where(Document.knowledge_base_id==kb_id).order_by(Document.updated_at.desc())))
@router.post("/knowledge-bases/{kb_id}/sources/approve-ready")
def approve_ready_sources(kb_id:uuid.UUID,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id);rows=list(db.scalars(select(Document).where(Document.knowledge_base_id==kb_id,Document.status=="ready")));now=datetime.now(timezone.utc)
    for row in rows: row.status="approved";row.approved_at=now
    if rows and kb.embedding_model_id: kb.reindex_required=True
    db.commit();return {"approved":len(rows)}
@router.post("/knowledge-bases/{kb_id}/sources/bulk")
def bulk_source_action(kb_id:uuid.UUID,p:BulkSourceAction,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id);rows=list(db.scalars(select(Document).where(Document.knowledge_base_id==kb_id,Document.id.in_(p.source_ids))));now=datetime.now(timezone.utc)
    if len(rows)!=len(set(p.source_ids)): raise HTTPException(404,"source_not_found")
    changed=0
    for row in rows:
        if p.action=="approve" and row.status=="ready": row.status="approved";row.approved_at=now;changed+=1
        elif p.action=="archive" and row.status!="archived": row.status="archived";row.enabled_in_retrieval=False;changed+=1
        elif p.action=="enable" and row.status=="approved" and not row.enabled_in_retrieval: row.enabled_in_retrieval=True;changed+=1
        elif p.action=="disable" and row.enabled_in_retrieval: row.enabled_in_retrieval=False;changed+=1
        row.updated_at=now
    if changed and kb.embedding_model_id: kb.reindex_required=True
    db.commit();return {"changed":changed,"action":p.action}
@router.get("/knowledge-bases/{kb_id}/sources/{source_id}")
def source_detail(kb_id:uuid.UUID,source_id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.scalar(select(Document).where(Document.id==source_id,Document.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"source_not_found")
    chunks=list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id==source_id).order_by(DocumentChunk.chunk_index)))
    return {"source":row,"chunks":chunks}

async def fetch_public_site(url:str):
    parsed=urlparse(url)
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password: raise HTTPException(422,"invalid_site_url")
    resolved=set()
    try:
        for item in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=="https" else 80)):
            ip=ipaddress.ip_address(item[4][0]);resolved.add(str(ip))
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: raise HTTPException(422,"site_host_must_be_public")
    except socket.gaierror: raise HTTPException(422,"site_host_unresolvable")
    data=bytearray();content_type="";encoding="utf-8"
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False) as client:
        async with client.stream("GET",url,headers={"User-Agent":"EZII-knowledge-ingestion","Accept":"text/html,text/plain"}) as response:
            response.raise_for_status();content_type=response.headers.get("content-type","").lower();encoding=response.encoding or "utf-8"
            stream=response.extensions.get("network_stream");address=stream.get_extra_info("server_addr") if stream and hasattr(stream,"get_extra_info") else None;peer=address[0] if address else None
            if peer not in resolved: raise HTTPException(502,"site_peer_mismatch")
            if content_type and not any(kind in content_type for kind in ("text/html","text/plain","application/xhtml+xml")): raise HTTPException(415,"unsupported_site_content_type")
            async for block in response.aiter_bytes():
                data.extend(block)
                if len(data)>settings.website_snapshot_max_bytes: raise HTTPException(413,"site_too_large")
    decoded=bytes(data).decode(encoding,errors="replace");text=BeautifulSoup(decoded,"html.parser").get_text(" ",strip=True)
    if not text: raise HTTPException(422,"site_has_no_text")
    return parsed,bytes(data),content_type,text

@router.post("/knowledge-bases/{kb_id}/sources/site",status_code=201)
async def add_site(kb_id:uuid.UUID,p:SiteIn,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id)
    if "website_snapshot" not in kb.knowledge_mode: raise HTTPException(409,"source_type_disabled")
    parsed,data,content_type,text=await fetch_public_site(p.url)
    row=Document(knowledge_base_id=kb.id,title=p.title or parsed.hostname,source_type="website_snapshot",mime_type=content_type,status="approved" if kb.publication_mode=="automatic" else "ready",checksum=hashlib.sha256(data).hexdigest(),metadata_json={"url":p.url});db.add(row);db.flush()
    add_text_chunks(db,row,text,kb.chunk_size_chars,kb.chunk_overlap_chars)
    if kb.embedding_model_id: kb.reindex_required=True
    db.commit();return {"id":str(row.id),"status":row.status,"title":row.title}

@router.post("/knowledge-bases/{kb_id}/sources/{source_id}/refresh")
async def refresh_source(kb_id:uuid.UUID,source_id:uuid.UUID,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id);row=db.scalar(select(Document).where(Document.id==source_id,Document.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"source_not_found")
    if row.source_type=="github_playbook": return await PlaybookSyncService(db).sync(kb_id)
    if row.source_type!="website_snapshot": raise HTTPException(409,"source_cannot_be_refreshed")
    url=(row.metadata_json or {}).get("url")
    if not url: raise HTTPException(409,"source_url_missing")
    _,data,content_type,text=await fetch_public_site(url);checksum=hashlib.sha256(data).hexdigest()
    if checksum==row.checksum: return {"id":str(row.id),"changed":False,"chunks":db.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id==row.id)) or 0}
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id==row.id));row.checksum=checksum;row.mime_type=content_type;row.updated_at=datetime.now(timezone.utc);count=add_text_chunks(db,row,text,kb.chunk_size_chars,kb.chunk_overlap_chars);kb.reindex_required=bool(kb.embedding_model_id);db.commit();return {"id":str(row.id),"changed":True,"chunks":count}

@router.post("/knowledge-bases/{kb_id}/playbook/sync")
async def sync_playbook(kb_id:uuid.UUID,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id)
    if "github_playbook" not in kb.knowledge_mode: raise HTTPException(409,"source_type_disabled")
    return await PlaybookSyncService(db).sync(kb_id)

@router.get("/knowledge-bases/{kb_id}/glossaries")
def glossaries(kb_id:uuid.UUID,db:Session=Depends(db_dep)): require_kb(db,kb_id);return list(db.scalars(select(Glossary).where(Glossary.knowledge_base_id==kb_id).order_by(Glossary.name)))
@router.post("/knowledge-bases/{kb_id}/glossaries",status_code=201)
def create_glossary(kb_id:uuid.UUID,p:GlossaryIn,db:Session=Depends(db_dep)):
    require_kb(db,kb_id)
    if p.is_default:
        for item in db.scalars(select(Glossary).where(Glossary.knowledge_base_id==kb_id,Glossary.is_default.is_(True))): item.is_default=False
    row=Glossary(knowledge_base_id=kb_id,**p.model_dump());db.add(row);commit_or_conflict(db,"glossary_name_exists");db.refresh(row);return row
@router.patch("/knowledge-bases/{kb_id}/glossaries/{glossary_id}")
def update_glossary(kb_id:uuid.UUID,glossary_id:uuid.UUID,p:GlossaryIn,db:Session=Depends(db_dep)):
    row=db.scalar(select(Glossary).where(Glossary.id==glossary_id,Glossary.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"glossary_not_found")
    if p.is_default:
        for item in db.scalars(select(Glossary).where(Glossary.knowledge_base_id==kb_id,Glossary.is_default.is_(True),Glossary.id!=glossary_id)): item.is_default=False
    for key,value in p.model_dump().items(): setattr(row,key,value)
    row.updated_at=datetime.now(timezone.utc);commit_or_conflict(db,"glossary_name_exists");db.refresh(row);return row
@router.delete("/knowledge-bases/{kb_id}/glossaries/{glossary_id}",status_code=204)
def delete_glossary(kb_id:uuid.UUID,glossary_id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.scalar(select(Glossary).where(Glossary.id==glossary_id,Glossary.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"glossary_not_found")
    db.delete(row);db.commit()
@router.get("/knowledge-bases/{kb_id}/glossaries/{glossary_id}/terms")
def terms(kb_id:uuid.UUID,glossary_id:uuid.UUID,db:Session=Depends(db_dep)):
    glossary=db.scalar(select(Glossary).where(Glossary.id==glossary_id,Glossary.knowledge_base_id==kb_id))
    if not glossary: raise HTTPException(404,"glossary_not_found")
    return list(db.scalars(select(GlossaryEntry).where(GlossaryEntry.glossary_id==glossary_id).order_by(GlossaryEntry.term)))
@router.post("/knowledge-bases/{kb_id}/glossaries/{glossary_id}/terms",status_code=201)
def create_term(kb_id:uuid.UUID,glossary_id:uuid.UUID,p:TermIn,db:Session=Depends(db_dep)):
    glossary=db.scalar(select(Glossary).where(Glossary.id==glossary_id,Glossary.knowledge_base_id==kb_id))
    if not glossary: raise HTTPException(404,"glossary_not_found")
    row=GlossaryEntry(glossary_id=glossary_id,**p.model_dump());db.add(row);db.commit();db.refresh(row);return row
@router.put("/knowledge-bases/{kb_id}/glossaries/{glossary_id}/terms/{term_id}")
def update_term(kb_id:uuid.UUID,glossary_id:uuid.UUID,term_id:uuid.UUID,p:TermIn,db:Session=Depends(db_dep)):
    row=db.scalar(select(GlossaryEntry).join(Glossary).where(GlossaryEntry.id==term_id,GlossaryEntry.glossary_id==glossary_id,Glossary.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"term_not_found")
    for key,value in p.model_dump().items(): setattr(row,key,value)
    row.updated_at=datetime.now(timezone.utc);db.commit();db.refresh(row);return row
@router.delete("/knowledge-bases/{kb_id}/glossaries/{glossary_id}/terms/{term_id}",status_code=204)
def delete_term(kb_id:uuid.UUID,glossary_id:uuid.UUID,term_id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.scalar(select(GlossaryEntry).join(Glossary).where(GlossaryEntry.id==term_id,GlossaryEntry.glossary_id==glossary_id,Glossary.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"term_not_found")
    db.delete(row);db.commit()

@router.post("/knowledge-bases/{kb_id}/sources/{source_id}/approve")
def approve_source(kb_id:uuid.UUID,source_id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.scalar(select(Document).where(Document.id==source_id,Document.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"source_not_found")
    row.status="approved";row.approved_at=datetime.now(timezone.utc);row.updated_at=row.approved_at;kb=require_kb(db,kb_id);kb.reindex_required=bool(kb.embedding_model_id);db.commit();return {"id":str(row.id),"status":row.status}

@router.delete("/knowledge-bases/{kb_id}/sources/{source_id}",status_code=204)
def delete_source(kb_id:uuid.UUID,source_id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.scalar(select(Document).where(Document.id==source_id,Document.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"source_not_found")
    path=Path(row.storage_path) if row.storage_path else None
    model_ids=set(db.scalars(select(DocumentChunk.embedding_model_id).where(DocumentChunk.document_id==row.id,DocumentChunk.embedding_model_id.is_not(None))))
    try:
        for model_id in model_ids: VectorService().delete_document(model_id,kb_id,row.id)
        safe_unlink(str(path) if path else None)
    except Exception as exc:
        for model_id in model_ids or {None}: db.add(StorageCleanupTask(knowledge_base_id=kb_id,document_id=row.id,storage_path=str(path) if path else None,vector_model_id=model_id,error_code=type(exc).__name__))
        db.commit();raise HTTPException(503,"source_cleanup_pending") from exc
    db.delete(row);db.commit()

@router.post("/knowledge-bases/{kb_id}/sources/{source_id}/archive")
def archive_source(kb_id:uuid.UUID,source_id:uuid.UUID,db:Session=Depends(db_dep)):
    row=db.scalar(select(Document).where(Document.id==source_id,Document.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"source_not_found")
    row.status="archived";row.enabled_in_retrieval=False;row.updated_at=datetime.now(timezone.utc);db.commit();return {"id":str(row.id),"status":row.status}
@router.post("/knowledge-bases/{kb_id}/sources/{source_id}/retrieval")
def toggle_source(kb_id:uuid.UUID,source_id:uuid.UUID,enabled:bool,db:Session=Depends(db_dep)):
    row=db.scalar(select(Document).where(Document.id==source_id,Document.knowledge_base_id==kb_id))
    if not row: raise HTTPException(404,"source_not_found")
    if enabled and row.status!="approved": raise HTTPException(409,"source_not_approved")
    row.enabled_in_retrieval=enabled;row.updated_at=datetime.now(timezone.utc);db.commit();return {"id":str(row.id),"enabled_in_retrieval":row.enabled_in_retrieval}

@router.post("/knowledge-bases/{kb_id}/reindex")
async def reindex(kb_id:uuid.UUID,db:Session=Depends(db_dep)):
    kb=require_kb(db,kb_id); model=db.get(ModelEndpoint,kb.embedding_model_id) if kb.embedding_model_id else None
    if not model or model.capability!="embedding" or not model.vector_size: raise HTTPException(409,"embedding_model_not_configured")
    chunks=list(db.scalars(select(DocumentChunk).join(Document).where(Document.knowledge_base_id==kb.id,Document.source_type.in_(kb.knowledge_mode),Document.status=="approved",Document.enabled_in_retrieval.is_(True))))
    prior_model_ids=set(db.scalars(select(DocumentChunk.embedding_model_id).join(Document).where(Document.knowledge_base_id==kb.id,DocumentChunk.embedding_model_id.is_not(None))));prior_model_ids.add(model.id)
    for prior_model_id in prior_model_ids: VectorService().delete_knowledge_base(prior_model_id,kb.id)
    if not chunks: kb.reindex_required=False;db.commit();return {"indexed":0}
    provider=provider_for(model,db); vectors=await provider.embeddings(model.model_id,[x.content for x in chunks]);
    if len(vectors)!=len(chunks) or any(len(v)!=model.vector_size for v in vectors): raise HTTPException(502,"embedding_dimension_mismatch")
    VectorService().upsert(model.id,model.vector_size,[{"id":str(c.id),"vector":v,"payload":{"knowledge_base_id":str(kb.id),"document_id":str(c.document_id),"chunk_id":str(c.id),"source_type":db.get(Document,c.document_id).source_type,"approved":True}} for c,v in zip(chunks,vectors)])
    for chunk in chunks: chunk.embedding_model_id=model.id;chunk.vector_size=model.vector_size
    kb.reindex_required=False;db.commit();return {"indexed":len(chunks)}

@router.post("/messages/{chat_id}",response_model=MessageOut)
async def answer(chat_id:uuid.UUID,p:MessageIn,db:Session=Depends(db_dep)):
    started=time.perf_counter();token_usage={}
    chat=db.get(Chat,chat_id)
    if not chat: raise HTTPException(404,"chat_not_found")
    kb=require_kb(db,chat.knowledge_base_id)
    history=list(db.scalars(select(Message).where(Message.chat_id==chat.id).order_by(Message.created_at.desc()).limit(kb.history_message_limit))) if kb.chat_context_enabled else [];history.reverse()
    budget=kb.history_token_budget;selected_history=[]
    for item in reversed(history):
        cost=max(1,len(item.content)//4)
        if cost>budget: break
        selected_history.append({"role":item.role,"content":item.content});budget-=cost
    selected_history.reverse();user=Message(chat_id=chat.id,role="user",content=p.content); db.add(user); db.flush()
    retrieval_started=time.perf_counter();chunks=list(db.scalars(select(DocumentChunk).join(Document).where(Document.knowledge_base_id==kb.id,Document.source_type.in_(kb.knowledge_mode),Document.status=="approved",Document.enabled_in_retrieval.is_(True))))
    glossary_rows=list(db.scalars(select(GlossaryEntry).join(Glossary).where(Glossary.knowledge_base_id==kb.id,Glossary.enabled.is_(True),GlossaryEntry.status=="active").order_by(Glossary.priority.desc(),GlossaryEntry.priority.desc())))
    ranked=[];warning_codes=[];vector_ranked=False;vector_hits=[]
    if kb.embedding_model_id and not kb.reindex_required:
        em=db.get(ModelEndpoint,kb.embedding_model_id)
        if em:
            try:
                query_vector=(await provider_for(em,db).embeddings(em.model_id,[p.content]))[0];vector_hits=VectorService().search(em.id,kb.id,query_vector);vector_ranked=bool(vector_hits)
            except Exception as exc:
                logger.warning("Vector retrieval unavailable knowledge_base_id=%s error_type=%s",kb.id,type(exc).__name__);warning_codes.append("vector_retrieval_unavailable")
                if kb.empty_retrieval_mode=="strict_fallback": raise HTTPException(503,"vector_retrieval_unavailable") from exc
    ranked_results=hybrid_rank(p.content,chunks,vector_hits,limit=8);ranked=[item.chunk for item in ranked_results]
    matching_terms=[x for x in glossary_rows if x.term.lower() in p.content.lower() or any(s.lower() in p.content.lower() for s in x.synonyms)];context="\n\n".join([*(f"TERM: {x.term}\nDEFINITION: {x.definition}" for x in matching_terms),*(x.content for x in ranked)])[:kb.context_token_budget*4];retrieval_ms=(time.perf_counter()-retrieval_started)*1000
    if not kb.chat_model_id: result="База знаний не настроена: выберите chat-модель в панели управления." if p.locale=="ru" else "The knowledge base is not configured: choose a chat model in Manage."
    elif not context and kb.empty_retrieval_mode in {"strict_fallback","clarifying_fallback"}: result=("В опубликованных источниках недостаточно данных. Уточните вопрос или добавьте источник." if p.locale=="ru" else "The published sources do not contain enough information. Clarify the question or add a source.")
    else:
        model=db.get(ModelEndpoint,kb.chat_model_id); conn=db.get(ModelConnection,model.connection_id) if model else None
        if not model or not conn: raise HTTPException(409,"chat_model_not_configured")
        provider=provider_for(model,db)
        result=await provider.answer(model.model_id,[{"role":"system","content":build_system_prompt(kb,context)},*selected_history,{"role":"user","content":p.content}]);token_usage=provider.last_usage
    source_ids=list(dict.fromkeys(str(x.document_id) for x in ranked));source_documents=[db.get(Document,source_id) for source_id in source_ids];source_documents=[source for source in source_documents if source and source.knowledge_base_id==kb.id];source_types=list(dict.fromkeys(source.source_type for source in source_documents));source_refs=[{"id":str(source.id),"title":source.title,"source_type":source.source_type} for source in source_documents];source_by_id={str(source.id):source for source in source_documents};ranked_refs=[{"chunk_id":str(item.chunk.id),"chunk_index":item.chunk.chunk_index,"source_id":str(item.chunk.document_id),"score":item.score,"lexical_score":item.lexical_score,"vector_score":item.vector_score} for item in ranked_results];citations=[{"chunk_id":str(item.chunk.id),"chunk_index":item.chunk.chunk_index,"source_id":str(item.chunk.document_id),"title":source_by_id[str(item.chunk.document_id)].title,"source_type":source_by_id[str(item.chunk.document_id)].source_type,"excerpt":item.chunk.content[:360],"score":item.score} for item in ranked_results if str(item.chunk.document_id) in source_by_id]
    retrieval_method="hybrid" if vector_ranked and any(item.lexical_score for item in ranked_results) else "vector" if vector_ranked else "text"
    out=Message(chat_id=chat.id,role="assistant",content=result,source_types=source_types,metadata_json={"source_ids":source_ids,"sources":source_refs,"citations":citations,"warning_codes":warning_codes});db.add(out);db.add(ResponseTrace(knowledge_base_id=kb.id,chat_id=chat.id,model_endpoint_id=kb.chat_model_id,answer_mode="grounded" if context else "model_only",source_types=source_types,source_ids=source_ids,ranking_scores={"query":p.content[:300],"matched_chunks":len(ranked),"vector_ranked":vector_ranked,"retrieval_method":retrieval_method,"retrieval_ms":round(retrieval_ms,1),"sources":source_refs,"ranked_chunks":ranked_refs},token_usage=token_usage,warning_codes=warning_codes,latency_ms=(time.perf_counter()-started)*1000,status="degraded" if warning_codes else "ok"));chat.updated_at=datetime.now(timezone.utc);db.commit();db.refresh(out);return out

@router.post("/messages/{chat_id}/stream")
async def answer_stream(chat_id:uuid.UUID,p:MessageIn,request:Request,db:Session=Depends(db_dep)):
    async def events():
        yield "event: ready\ndata: {}\n\n"
        if await request.is_disconnected(): return
        try:
            message=await answer(chat_id,p,db)
            payload=MessageOut.model_validate(message).model_dump(mode="json")
            yield f"event: message\ndata: {json.dumps(payload,ensure_ascii=False)}\n\n"
        except HTTPException as exc:
            yield f"event: error\ndata: {json.dumps({'detail':exc.detail},ensure_ascii=False)}\n\n"
        except Exception:
            db.rollback();logger.exception("Streaming answer failed chat_id=%s",chat_id)
            yield 'event: error\ndata: {"detail":"provider_unavailable"}\n\n'
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
