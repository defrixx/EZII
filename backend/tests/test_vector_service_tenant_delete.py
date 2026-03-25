from app.services.vector_service import VectorService


def test_delete_entry_skips_delete_when_tenant_mismatch():
    service = VectorService.__new__(VectorService)
    service.collection = "glossary_entries"

    class FakeClient:
        def __init__(self):
            self.deleted = False

        def retrieve(self, collection_name, ids, with_payload):
            assert collection_name == "glossary_entries"
            assert ids == ["entry-1"]
            assert with_payload is True
            return [type("Point", (), {"payload": {"tenant_id": "tenant-a"}})()]

        def delete(self, collection_name, points_selector, wait):
            self.deleted = True

    fake = FakeClient()
    service.client = fake

    service.delete_entry("entry-1", tenant_id="tenant-b")

    assert fake.deleted is False


def test_delete_entry_deletes_when_tenant_matches():
    service = VectorService.__new__(VectorService)
    service.collection = "glossary_entries"

    class FakeClient:
        def __init__(self):
            self.deleted = False
            self.points_selector = None

        def retrieve(self, collection_name, ids, with_payload):
            return [type("Point", (), {"payload": {"tenant_id": "tenant-a"}})()]

        def delete(self, collection_name, points_selector, wait):
            self.deleted = True
            self.points_selector = points_selector
            assert collection_name == "glossary_entries"
            assert wait is True

    fake = FakeClient()
    service.client = fake

    service.delete_entry("entry-1", tenant_id="tenant-a")

    assert fake.deleted is True
    assert fake.points_selector == ["entry-1"]
