import uuid
import asyncio

from app.core.logging_utils import redact_pii
from app.services.retrieval_service import RetrievalService


class DummyGlossary:
    def __init__(self, term: str, definition: str, priority: int = 100, glossary_priority: int = 100):
        self.id = uuid.uuid4()
        self.term = term
        self.definition = definition
        self.priority = priority
        self.glossary_id = uuid.uuid4()
        self.glossary_priority = glossary_priority
        self.glossary_name = "Default"


def test_normalize_query_strips_injection_tokens():
    q = "  What is `MVP`   <script>  "
    out = RetrievalService.normalize_query(q)
    assert out == "what is mvp script"


def test_score_priority_order_exact_syn_semantic():
    exact_row = DummyGlossary(term="MVP", definition="d1", priority=10)
    syn_row = DummyGlossary(term="Product", definition="d2", priority=10)
    exact = [
        {
            "id": str(exact_row.id),
            "term": exact_row.term,
            "definition": exact_row.definition,
            "entry_priority": exact_row.priority,
            "glossary_id": str(exact_row.glossary_id),
            "glossary_priority": exact_row.glossary_priority,
            "glossary_name": exact_row.glossary_name,
        }
    ]
    synonym = [
        {
            "id": str(syn_row.id),
            "term": syn_row.term,
            "definition": syn_row.definition,
            "entry_priority": syn_row.priority,
            "glossary_id": str(syn_row.glossary_id),
            "glossary_priority": syn_row.glossary_priority,
            "glossary_name": syn_row.glossary_name,
        }
    ]
    semantic = [
        {
            "id": str(uuid.uuid4()),
            "score": 0.9,
            "payload": {
                "term": "Approx",
                "definition": "d3",
                "entry_priority": 100,
                "glossary_priority": 100,
                "glossary_id": str(uuid.uuid4()),
                "glossary_name": "Default",
            },
        }
    ]

    ranked = RetrievalService._score(exact, synonym, semantic)
    assert ranked[0]["source"] == "exact"
    assert ranked[1]["source"] == "synonym"
    assert ranked[2]["source"] == "semantic"


def test_redact_pii():
    text = "Contact john.doe@example.com or +1 (555) 123-4567"
    redacted = redact_pii(text)
    assert "example.com" not in redacted
    assert "555" not in redacted
    assert "[REDACTED]" in redacted


class StubGlossaryRepo:
    def list_enabled_glossaries(self, tenant_id: str):
        return []

    def exact_match(self, tenant_id: str, normalized_query: str, glossary_ids: list[str]):
        return []

    def synonym_match(self, tenant_id: str, normalized_query: str, glossary_ids: list[str]):
        return []


class StubAdminRepo:
    def list_allowlist(self, tenant_id: str):
        return []


class StubWeb:
    async def fetch_allowed(self, query: str, allowlist: list[str]):
        return [], []


class StubProvider:
    async def embeddings(self, inputs: list[str]):
        return [[0.1, 0.2, 0.3]]


class StubVector:
    def search(self, tenant_id: str, vector: list[float], limit: int, glossary_ids: list[str] | None = None):
        raise AssertionError("Vector search should not be called when no enabled glossaries")


def test_run_skips_vector_search_when_all_glossaries_disabled():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.web = StubWeb()
    retrieval.vector = StubVector()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(retrieval.run("tenant-1", "test query", strict_glossary_mode=False, web_enabled=False))
    assert out["top_glossary"] == []
