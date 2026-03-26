from fastapi.testclient import TestClient

from app.api.deps import db_dep
from app.core.security import AuthContext, require_admin
from app.main import app


def _admin_ctx() -> AuthContext:
    return AuthContext(
        user_id="admin-1",
        tenant_id="tenant-1",
        email="admin@example.com",
        role="admin",
    )


def test_admin_qdrant_reset_all_recreates_default_collections(monkeypatch):
    from app.api.v1 import admin as admin_module

    calls: dict[str, list] = {"deleted": [], "created": []}

    class FakeCollections:
        collections = [type("C", (), {"name": "legacy_a"})(), type("C", (), {"name": "legacy_b"})()]

    class FakeQdrantClient:
        def __init__(self, url: str, timeout: float):
            assert url == admin_module.settings.qdrant_url
            assert timeout == admin_module.settings.qdrant_timeout_s

        def get_collections(self):
            return FakeCollections()

        def delete_collection(self, collection_name: str):
            calls["deleted"].append(collection_name)

        def create_collection(self, collection_name: str, vectors_config):
            calls["created"].append((collection_name, int(vectors_config.size)))

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def add_audit_log(self, *args, **kwargs):
            return None

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "QdrantClient", FakeQdrantClient)
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module.settings, "default_tenant_id", "tenant-1")

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/admin/qdrant/reset-all",
            json={
                "embedding_vector_size": 1024,
                "confirm_phrase": "DELETE ALL QDRANT COLLECTIONS",
                "confirm_phrase_repeat": "DELETE ALL QDRANT COLLECTIONS",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["deleted_collections"] == ["legacy_a", "legacy_b"]
        assert payload["recreated_collections"] == [
            admin_module.settings.qdrant_collection,
            admin_module.settings.qdrant_documents_collection,
        ]
        assert payload["embedding_vector_size"] == 1024
        assert calls["deleted"] == ["legacy_a", "legacy_b"]
        assert calls["created"] == [
            (admin_module.settings.qdrant_collection, 1024),
            (admin_module.settings.qdrant_documents_collection, 1024),
        ]
    finally:
        app.dependency_overrides.clear()


def test_admin_qdrant_reset_all_requires_double_confirmation(monkeypatch):
    from app.api.v1 import admin as admin_module

    class FakeAdminRepository:
        def __init__(self, db):
            self.db = db

        def add_audit_log(self, *args, **kwargs):
            return None

    app.dependency_overrides[require_admin] = _admin_ctx
    app.dependency_overrides[db_dep] = lambda: object()
    monkeypatch.setattr(admin_module, "AdminRepository", FakeAdminRepository)
    monkeypatch.setattr(admin_module.settings, "default_tenant_id", "tenant-1")

    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/admin/qdrant/reset-all",
            json={
                "embedding_vector_size": 1024,
                "confirm_phrase": "DELETE ALL QDRANT COLLECTIONS",
                "confirm_phrase_repeat": "WRONG",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid second confirmation phrase"
    finally:
        app.dependency_overrides.clear()
