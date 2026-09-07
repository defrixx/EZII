import hashlib
from pathlib import PurePosixPath
from urllib.parse import quote
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Document,DocumentChunk,KnowledgeBase
from app.services.ingestion_service import add_text_chunks

class PlaybookSyncService:
    owner="defrixx"; repo="Product-security-playbook"; branch="main"; max_files=200; max_bytes=100*1024*1024
    def __init__(self,db:Session): self.db=db
    @classmethod
    def allowed(cls,path:str):
        p=PurePosixPath(path);suffix=p.name.lower()
        return not p.is_absolute() and ".." not in p.parts and not any(x.startswith(".") for x in p.parts) and p.parts[0] in {"content","reference"} and suffix.endswith((".en.md",".ru.md"))
    @staticmethod
    def title(path:str):
        p=PurePosixPath(path);language="RU" if p.name.lower().endswith(".ru.md") else "EN";subject=p.parent.name if p.stem.lower().split(".")[0] in {"playbook","overview","checklist"} else p.name.rsplit(".",2)[0]
        return f"{subject.replace('-',' ').title()} [{language}]"
    async def sync(self,knowledge_base_id):
        kb=self.db.get(KnowledgeBase,knowledge_base_id)
        if not kb: raise HTTPException(404,"knowledge_base_not_found")
        headers={"User-Agent":"EZII-playbook-sync","Accept":"application/vnd.github+json"}
        # The fixed GitHub repository currently redirects to its canonical numeric API URL.
        # Redirects are safe here because every requested URL is constructed from constants.
        async with httpx.AsyncClient(timeout=30,follow_redirects=True) as c:
            commit=await c.get(f"https://api.github.com/repos/{self.owner}/{self.repo}/commits/{self.branch}",headers=headers); commit.raise_for_status(); sha=commit.json()["sha"]
            tree=await c.get(f"https://api.github.com/repos/{self.owner}/{self.repo}/git/trees/{sha}?recursive=1",headers=headers); tree.raise_for_status()
            paths=sorted(x["path"] for x in tree.json().get("tree",[]) if x.get("type")=="blob" and self.allowed(x.get("path","")))
            if len(paths)>self.max_files: raise HTTPException(413,"playbook_file_limit")
            existing=list(self.db.scalars(select(Document).where(Document.knowledge_base_id==kb.id,Document.source_type=="github_playbook"))); by_path={(x.metadata_json or {}).get("path"):x for x in existing}; seen=set(); total=0; changed=0
            for path in paths:
                response=await c.get(f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{sha}/{quote(path,safe='/')}",headers=headers); response.raise_for_status(); data=response.content; total+=len(data)
                if total>self.max_bytes: raise HTTPException(413,"playbook_size_limit")
                checksum=hashlib.sha256(data).hexdigest(); seen.add(path); row=by_path.get(path)
                if row and row.checksum==checksum:
                    row.title=self.title(path);continue
                if not row: row=Document(knowledge_base_id=kb.id,title=self.title(path),source_type="github_playbook");self.db.add(row);self.db.flush()
                else:
                    for chunk in self.db.scalars(select(DocumentChunk).where(DocumentChunk.document_id==row.id)): self.db.delete(chunk)
                row.checksum=checksum;row.status="approved" if kb.publication_mode=="automatic" else "ready";row.enabled_in_retrieval=True;row.metadata_json={"repository":f"{self.owner}/{self.repo}","path":path,"commit_sha":sha}
                text=data.decode("utf-8",errors="replace")
                add_text_chunks(self.db,row,text,kb.chunk_size_chars,kb.chunk_overlap_chars)
                changed+=1
            for row in existing:
                if (row.metadata_json or {}).get("path") not in seen: row.status="archived"
            if changed and kb.embedding_model_id: kb.reindex_required=True
            self.db.commit();return {"repository":f"{self.owner}/{self.repo}","commit_sha":sha,"files":len(paths),"changed":changed}
