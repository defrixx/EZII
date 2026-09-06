import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.api.v1.router import ChatPatch, ConnectionIn, KBIn, ModelIn
from app.models import Chat, Document, DocumentChunk, IngestionJob, KnowledgeBase, Message, ModelConnection, ModelEndpoint, StorageCleanupTask
from app.main import app
from app.main import local_hostname
from app.services.playbook_sync_service import PlaybookSyncService
from app.services.provider_service import validate_base_url
from app.services.vector_service import VectorService

def test_auth_and_tenant_models_are_gone():
    import app.models as models
    assert not hasattr(models,"Tenant"); assert not hasattr(models,"User")
    assert "tenant_id" not in KnowledgeBase.__table__.columns
    assert "user_id" not in Chat.__table__.columns
    assert "user_id" not in Message.__table__.columns

def test_knowledge_scopes_are_required():
    assert not Document.__table__.columns["knowledge_base_id"].nullable
    assert not Chat.__table__.columns["knowledge_base_id"].nullable

def test_chat_patch_cannot_change_knowledge_base():
    assert "knowledge_base_id" not in ChatPatch.model_fields
    with pytest.raises(Exception): ChatPatch.model_validate({"knowledge_base_id":"00000000-0000-0000-0000-000000000001"})

def test_connection_secret_is_never_an_output_field():
    from app.api.v1.router import ConnectionOut
    assert "api_key" not in ConnectionOut.model_fields
    assert "has_api_key" in ConnectionOut.model_fields

@pytest.mark.parametrize("url",["http://host.docker.internal:1234/v1","http://localhost:1234/v1","http://127.0.0.1:1234/v1"])
def test_lm_studio_local_urls(url): assert validate_base_url("lm_studio",url,{"host.docker.internal","localhost","127.0.0.1"})==url

def test_cloud_http_is_rejected():
    with pytest.raises(ValueError,match="https"): validate_base_url("openrouter","http://openrouter.ai/api/v1",set())

def test_lm_studio_public_host_is_rejected():
    with pytest.raises(ValueError,match="local"): validate_base_url("lm_studio","http://example.com/v1",{"localhost"})

@pytest.mark.parametrize("url",["http://user:secret@localhost:1234/v1","http://localhost:1234/v1?token=secret","http://localhost:1234/v1#fragment"])
def test_provider_url_cannot_hide_credentials_or_routing_data(url):
    with pytest.raises(ValueError,match="invalid_provider_url"): validate_base_url("lm_studio",url,{"localhost"})

def test_embedding_model_requires_vector_size():
    with pytest.raises(Exception): ModelIn(connection_id="00000000-0000-0000-0000-000000000001",name="e",model_id="e",capability="embedding")

def test_playbook_only_accepts_expected_safe_markdown():
    assert PlaybookSyncService.allowed("guides/example.en.md")
    assert not PlaybookSyncService.allowed(".github/workflows/release.en.md")
    assert not PlaybookSyncService.allowed("../secret.en.md")

def test_database_contracts():
    assert set(ModelConnection.__table__.columns.keys()) >= {"kind","base_url","api_key"}
    assert set(ModelEndpoint.__table__.columns.keys()) >= {"capability","vector_size"}
    assert set(DocumentChunk.__table__.columns.keys()) >= {"embedding_model_id","vector_size"}
    assert not IngestionJob.__table__.columns["knowledge_base_id"].nullable
    assert not StorageCleanupTask.__table__.columns["knowledge_base_id"].nullable
    assert {index.name for index in KnowledgeBase.__table__.indexes}>={"uq_kb_name_ci","uq_kb_default"}

def test_qdrant_search_is_scoped_to_knowledge_base_and_approval():
    captured={}
    class Client:
        def search(self,**kwargs): captured.update(kwargs);return []
    service=VectorService.__new__(VectorService);service.client=Client()
    service.search("00000000-0000-0000-0000-000000000001","00000000-0000-0000-0000-000000000002",[0.0,1.0])
    conditions=captured["query_filter"].must
    assert {(item.key,item.match.value) for item in conditions}=={
        ("knowledge_base_id","00000000-0000-0000-0000-000000000002"),("approved",True)
    }

def test_qdrant_delete_is_scoped_to_knowledge_base_and_document():
    captured={}
    class Client:
        def get_collections(self): return SimpleNamespace(collections=[SimpleNamespace(name=VectorService.collection("00000000-0000-0000-0000-000000000001"))])
        def delete(self,name,selector,wait): captured.update(name=name,selector=selector,wait=wait)
    service=VectorService.__new__(VectorService);service.client=Client()
    service.delete_document("00000000-0000-0000-0000-000000000001","00000000-0000-0000-0000-000000000002","00000000-0000-0000-0000-000000000003")
    conditions=captured["selector"].filter.must
    assert {(item.key,item.match.value) for item in conditions}=={
        ("knowledge_base_id","00000000-0000-0000-0000-000000000002"),("document_id","00000000-0000-0000-0000-000000000003")
    }

def test_qdrant_collection_is_recreated_when_embedding_dimension_changes():
    actions=[];name=VectorService.collection("00000000-0000-0000-0000-000000000001")
    class Client:
        def get_collections(self): return SimpleNamespace(collections=[SimpleNamespace(name=name)])
        def get_collection(self,_): return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=3))))
        def delete_collection(self,value): actions.append(("delete",value))
        def create_collection(self,value,vectors_config): actions.append(("create",value,vectors_config.size))
    service=VectorService.__new__(VectorService);service.client=Client()
    assert service.ensure("00000000-0000-0000-0000-000000000001",4)==name
    assert actions==[("delete",name),("create",name,4)]

def test_provider_secret_is_encrypted_and_round_trips(monkeypatch):
    from cryptography.fernet import Fernet
    import app.core.secret_crypto as crypto
    key=Fernet.generate_key().decode();monkeypatch.setattr(crypto,"get_settings",lambda:SimpleNamespace(provider_api_key_encryption_key=key))
    encrypted=crypto.encrypt_secret("private-token")
    assert encrypted.startswith("enc:v1:") and "private-token" not in encrypted
    assert crypto.decrypt_secret(encrypted)=="private-token"

def test_required_local_api_contracts_exist():
    routes={(method,route.path) for route in app.routes for method in getattr(route,"methods",set())}
    required={
        ("GET","/api/v1/knowledge-bases/{id}"),
        ("GET","/api/v1/knowledge-bases/{id}/index-status"),
        ("GET","/api/v1/settings/connections/{id}/models"),
        ("POST","/api/v1/messages/{chat_id}/stream"),
        ("DELETE","/api/v1/settings/models/{id}"),
        ("GET","/api/v1/maintenance/status"),
        ("POST","/api/v1/maintenance/retry-cleanup"),
    }
    assert required <= routes

def test_runtime_routes_have_no_auth_surface():
    paths={route.path for route in app.routes}
    assert not any(any(marker in path for marker in ("/auth","/login","/logout","/register")) for path in paths)

def test_cleanup_never_unlinks_outside_document_storage(monkeypatch,tmp_path):
    import app.services.cleanup_service as cleanup
    root=tmp_path/"storage";root.mkdir();outside=tmp_path/"outside.txt";outside.write_text("keep")
    monkeypatch.setattr(cleanup,"get_settings",lambda:SimpleNamespace(document_storage_path=str(root)))
    with pytest.raises(ValueError,match="outside_storage"): cleanup.safe_unlink(str(outside))
    assert outside.read_text()=="keep"

def test_validation_errors_strip_raw_secret_input():
    from app.core.errors import _sanitize_validation_detail
    sanitized=_sanitize_validation_detail([{"loc":["body","api_key"],"msg":"bad","input":"top-secret"}])
    assert "top-secret" not in str(sanitized) and "input" not in sanitized[0]

@pytest.mark.parametrize("host",["localhost:8080","127.0.0.1:8080","[::1]:8080","backend:8000","http://localhost:8080"])
def test_local_access_hosts_are_accepted(host):
    assert local_hostname(host)

@pytest.mark.parametrize("host",["evil.example","localhost.evil.example","127.0.0.1.evil.example","", "http://evil.example"])
def test_non_local_access_hosts_are_rejected(host):
    assert not local_hostname(host)

def test_cross_site_mutation_is_blocked_and_security_headers_are_set():
    client=TestClient(app)
    blocked=client.post("/health",headers={"Origin":"https://evil.example","Sec-Fetch-Site":"cross-site"})
    assert blocked.status_code==403
    response=client.get("/health")
    assert response.status_code==200
    assert response.headers["x-frame-options"]=="DENY"
    assert response.headers["x-content-type-options"]=="nosniff"
