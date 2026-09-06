from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance,FieldCondition,Filter,FilterSelector,MatchValue,PointStruct,VectorParams
from app.core.config import get_settings
class VectorService:
 def __init__(self): self.client=QdrantClient(url=get_settings().qdrant_url,timeout=5)
 @staticmethod
 def collection(model_id): return "kb_"+str(model_id).replace("-","")
 def ensure(self,model_id,size):
  name=self.collection(model_id); names={x.name for x in self.client.get_collections().collections}
  if name in names:
   configured=self.client.get_collection(name).config.params.vectors
   configured_size=getattr(configured,"size",None)
   if configured_size!=size:self.client.delete_collection(name);names.remove(name)
  if name not in names:self.client.create_collection(name,vectors_config=VectorParams(size=size,distance=Distance.COSINE))
  return name
 def upsert(self,model_id,size,rows): self.client.upsert(self.ensure(model_id,size),[PointStruct(id=x["id"],vector=x["vector"],payload=x["payload"]) for x in rows],wait=True)
 def search(self,model_id,kb_id,vector,limit=6):
  result=self.client.search(collection_name=self.collection(model_id),query_vector=vector,limit=limit,query_filter=Filter(must=[FieldCondition(key="knowledge_base_id",match=MatchValue(value=str(kb_id))),FieldCondition(key="approved",match=MatchValue(value=True))]))
  return [{"score":float(x.score),"payload":x.payload or {}} for x in result]
 def delete_document(self,model_id,kb_id,document_id):
  name=self.collection(model_id)
  if name not in {x.name for x in self.client.get_collections().collections}: return
  self.client.delete(name,FilterSelector(filter=Filter(must=[FieldCondition(key="knowledge_base_id",match=MatchValue(value=str(kb_id))),FieldCondition(key="document_id",match=MatchValue(value=str(document_id)))])),wait=True)
 def delete_knowledge_base(self,model_id,kb_id):
  name=self.collection(model_id)
  if name not in {x.name for x in self.client.get_collections().collections}: return
  self.client.delete(name,FilterSelector(filter=Filter(must=[FieldCondition(key="knowledge_base_id",match=MatchValue(value=str(kb_id)))])),wait=True)
 def delete_model_collection(self,model_id):
  name=self.collection(model_id)
  if name in {x.name for x in self.client.get_collections().collections}: self.client.delete_collection(name)
