import uuid
import asyncio
from types import SimpleNamespace

from app.core.logging_utils import redact_pii
from app.services.retrieval_service import RetrievalService
from app.services.vector_service import VectorStoreError


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


def test_build_prompt_includes_conversation_history_as_separate_context():
    prompt = RetrievalService.build_prompt(
        query="How is this interpreted in our policy?",
        context="INTERNAL GLOSSARY: DevSecOps ...",
        conversation_history=[
            {"role": "user", "content": "What does DevSecOps mean?"},
            {"role": "assistant", "content": "It is the integration of security practices into DevOps."},
        ],
        knowledge_mode="glossary_documents",
        strict_glossary_mode=False,
        response_tone="consultative_supportive",
        intent="semantic_lookup",
    )
    assert prompt[0]["role"] == "system"
    assert "conversational context" in prompt[1]["content"]
    assert prompt[2]["role"] == "user"
    assert prompt[3]["role"] == "assistant"
    assert prompt[-2]["content"] == "INTERNAL GLOSSARY: DevSecOps ..."
    assert prompt[-1]["content"] == "How is this interpreted in our policy?"


def test_clean_rewritten_query_strips_common_prefixes():
    rewritten = RetrievalService._clean_rewritten_query(
        "how is this interpreted in our policy?",
        "Standalone query: What does devsecops mean in our policy?\n\nExplanation",
    )
    assert rewritten == "What does devsecops mean in our policy?"


class StubGlossaryRepo:
    def list_enabled_glossaries(self, tenant_id: str):
        return []

    def exact_match(self, tenant_id: str, normalized_query: str, glossary_ids: list[str]):
        return []

    def synonym_match(self, tenant_id: str, normalized_query: str, glossary_ids: list[str]):
        return []


class StubAdminRepo:
    def search_document_chunks_text(self, tenant_id: str, normalized_query: str, source_type: str, limit: int = 5):
        return []


class StubProvider:
    async def embeddings(self, inputs: list[str]):
        return [[0.1, 0.2, 0.3]]


class StubVector:
    def search(self, tenant_id: str, vector: list[float], limit: int, glossary_ids: list[str] | None = None):
        raise AssertionError("Vector search should not be called when no enabled glossaries")


class StubDocumentVector:
    def __init__(self):
        self.calls = []

    def search(self, tenant_id: str, vector: list[float], limit: int, glossary_ids: list[str] | None = None, filters: dict | None = None):
        self.calls.append({"tenant_id": tenant_id, "limit": limit, "filters": filters or {}})
        if filters and filters.get("source_type") == "github_playbook":
            return []
        if filters and filters.get("source_type") == "website_snapshot":
            return [
                {
                    "id": str(uuid.uuid4()),
                    "score": 0.77,
                    "payload": {
                        "chunk_id": "snapshot-chunk-1",
                        "document_id": "site-1",
                        "web_snapshot_id": "site-1",
                        "title": "Vendor FAQ Snapshot",
                        "content": "Pricing changes are published every quarter.",
                        "section": "Pricing",
                        "domain": "vendor.example.com",
                    },
                }
            ]
        return [
            {
                "id": str(uuid.uuid4()),
                "score": 0.88,
                "payload": {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "title": "Policy Handbook",
                    "content": "Employees must submit expenses within 10 days.",
                    "page": 4,
                    "section": "Expenses",
                },
            }
        ]


class StubDocumentVectorMany:
    def __init__(self):
        self.calls = []

    def search(self, tenant_id: str, vector: list[float], limit: int, glossary_ids: list[str] | None = None, filters: dict | None = None):
        self.calls.append({"tenant_id": tenant_id, "limit": limit, "filters": filters or {}})
        source_type = (filters or {}).get("source_type")
        if source_type in {"website_snapshot", "github_playbook"}:
            return []
        hits = []
        for idx in range(25):
            hits.append(
                {
                    "id": str(uuid.uuid4()),
                    "score": 0.6 + (idx / 1000),
                    "payload": {
                        "chunk_id": f"chunk-{idx}",
                        "document_id": f"doc-{idx}",
                        "title": f"Policy Handbook {idx}",
                        "content": f"Item {idx} description",
                        "page": idx + 1,
                        "section": "Top Risks",
                    },
                }
            )
        return hits[:limit]


def test_run_skips_vector_search_when_all_glossaries_disabled():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = StubDocumentVector()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "test query",
            knowledge_mode="glossary_documents",
            strict_glossary_mode=False,
        )
    )
    assert out["top_glossary"] == []
    assert out["top_documents"][0]["title"] == "Policy Handbook"
    assert "Employees must submit expenses" in out["assembled_context"]


def test_run_includes_website_snapshot_context_when_enabled():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = StubDocumentVector()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "pricing query",
            knowledge_mode="glossary_documents_web",
            strict_glossary_mode=False,
        )
    )
    assert out["top_websites"][0]["title"] == "Vendor FAQ Snapshot"
    assert out["web_snapshot_ids"] == ["site-1"]
    assert "Pricing changes are published every quarter." in out["assembled_context"]


class StubDocumentVectorWithPlaybook(StubDocumentVector):
    def search(self, tenant_id: str, vector: list[float], limit: int, glossary_ids: list[str] | None = None, filters: dict | None = None):
        self.calls.append({"tenant_id": tenant_id, "limit": limit, "filters": filters or {}})
        if filters and filters.get("source_type") == "github_playbook":
            return [
                {
                    "id": str(uuid.uuid4()),
                    "score": 0.7,
                    "payload": {
                        "chunk_id": "playbook-chunk-1",
                        "document_id": "playbook-1",
                        "title": "OWASP Top 10 Playbook",
                        "content": "Use the GitHub playbook remediation steps first.",
                        "section": "Remediation",
                    },
                }
            ]
        return super().search(tenant_id, vector, limit, glossary_ids=glossary_ids, filters=filters)


def test_run_github_documents_web_mode_prioritizes_playbooks_before_documents_and_websites():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = StubDocumentVectorWithPlaybook()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "remediation query",
            knowledge_mode="glossary_github_documents_web",
            strict_glossary_mode=False,
        )
    )

    assert out["source_types"] == ["github_playbook", "upload", "website"]
    assert out["ranking_scores"]["github_playbooks"]
    assert (
        out["assembled_context"].index("GITHUB PLAYBOOKS")
        < out["assembled_context"].index("INTERNAL DOCUMENTS")
        < out["assembled_context"].index("APPROVED WEBSITE SNAPSHOTS")
    )


def test_run_glossary_only_excludes_documents_and_websites():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = StubDocumentVector()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "policy query",
            knowledge_mode="glossary_only",
            strict_glossary_mode=False,
        )
    )
    assert out["top_documents"] == []
    assert out["top_websites"] == []
    assert out["source_types"] == []


def test_run_document_hit_uses_document_aware_confidence():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = StubDocumentVector()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "expense policy",
            knowledge_mode="glossary_documents",
            strict_glossary_mode=False,
        )
    )
    assert out["top_glossary"] == []
    assert out["top_documents"]
    assert out["top_documents"][0]["source"] == "upload_semantic"
    assert out["confidence"] in {"medium", "high"}
    assert out["source_types"] == ["upload"]


def test_confidence_for_upload_text_fallback_is_not_forced_to_low():
    text_fallback_hits = RetrievalService._score_documents(
        [
            {
                "id": "chunk-1",
                "content": "Receipts are required for reimbursement.",
                "document_id": "doc-1",
            }
        ],
        source_tag="upload",
    )

    assert text_fallback_hits[0]["source"] == "upload_text"
    assert text_fallback_hits[0]["score"] == 0.52
    assert RetrievalService._confidence(text_fallback_hits) == "medium"


def test_run_applies_only_approved_enabled_filters_for_documents_and_sites():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = StubDocumentVector()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "vendor policy",
            knowledge_mode="glossary_documents_web",
            strict_glossary_mode=False,
        )
    )

    assert len(retrieval.document_vector.calls) == 2
    assert retrieval.document_vector.calls[0]["filters"] == {
        "source_type": "upload",
        "status": "approved",
        "enabled_in_retrieval": True,
    }
    assert retrieval.document_vector.calls[1]["filters"] == {
        "source_type": "website_snapshot",
        "status": "approved",
        "enabled_in_retrieval": True,
    }
    assert out["document_ids"] == ["doc-1"]
    assert out["web_snapshot_ids"] == ["site-1"]


def test_run_uses_dynamic_limits_for_list_queries():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = StubAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = StubDocumentVectorMany()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "give top 10 owasp llm vulnerabilities",
            knowledge_mode="glossary_documents",
            strict_glossary_mode=False,
        )
    )

    assert out["intent"] == "list_query"
    assert out["requested_items"] == 10
    assert len(out["top_documents"]) == 10
    assert retrieval.document_vector.calls[0]["limit"] == 15


def test_ranking_priority_is_glossary_then_document_then_website():
    glossary_row = DummyGlossary(term="Expense policy", definition="Use the approved reimbursement process.")
    exact = [
        {
            "id": str(glossary_row.id),
            "term": glossary_row.term,
            "definition": glossary_row.definition,
            "entry_priority": glossary_row.priority,
            "glossary_id": str(glossary_row.glossary_id),
            "glossary_priority": glossary_row.glossary_priority,
            "glossary_name": glossary_row.glossary_name,
        }
    ]
    glossary_ranked = RetrievalService._score(exact, [], [])
    documents = RetrievalService._score_documents(
        [
            {
                "id": str(uuid.uuid4()),
                "score": 0.9,
                "payload": {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "title": "Expense Regulation",
                    "content": "Receipts are required.",
                    "page": 2,
                    "section": "Approval",
                },
            }
        ],
        source_tag="upload",
    )
    websites = RetrievalService._score_documents(
        [
            {
                "id": str(uuid.uuid4()),
                "score": 0.9,
                "payload": {
                    "chunk_id": "site-chunk-1",
                    "document_id": "site-1",
                    "web_snapshot_id": "site-1",
                    "title": "Vendor FAQ",
                    "content": "Invoices are issued monthly.",
                    "section": "Billing",
                    "domain": "vendor.example.com",
                },
            }
        ],
        source_tag="website",
    )

    assert glossary_ranked[0]["score"] > documents[0]["score"] > websites[0]["score"]

    context = RetrievalService._assemble_context(glossary_ranked, [], documents, websites, strict_glossary_mode=False)
    assert context.index("INTERNAL GLOSSARY") < context.index("INTERNAL DOCUMENTS") < context.index("APPROVED WEBSITE SNAPSHOTS")


def test_provider_for_tenant_fails_closed_when_provider_missing():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.settings = SimpleNamespace(
        openrouter_base_url="https://openrouter.example.com",
        openrouter_api_key="global-key-should-not-be-used",
        openrouter_model="model",
        openrouter_embedding_model="embedding",
        provider_timeout_s=30,
        provider_max_retries=2,
    )
    retrieval.a_repo = SimpleNamespace(get_provider=lambda tenant_id: None)
    retrieval.db = object()

    try:
        retrieval._provider_for_tenant("tenant-1")
        assert False, "Expected missing provider to fail closed"
    except RuntimeError as exc:
        assert "not configured" in str(exc).lower()


class FailingDocumentVector:
    def search(self, tenant_id: str, vector: list[float], limit: int, glossary_ids: list[str] | None = None, filters: dict | None = None):
        raise VectorStoreError("qdrant unavailable")


class FallbackAdminRepo:
    def search_document_chunks_text(self, tenant_id: str, normalized_query: str, source_type: str, limit: int = 5):
        return [
            {
                "id": "text-hit-1",
                "document_id": "doc-text-1",
                "web_snapshot_id": "",
                "title": "Fallback Policy",
                "content": "Fallback match from DB text search.",
                "page": 1,
                "section": "Intro",
                "domain": None,
                "url": None,
            }
        ]


def test_run_sets_retrieval_degraded_and_falls_back_to_text_search():
    retrieval = RetrievalService.__new__(RetrievalService)
    retrieval.g_repo = StubGlossaryRepo()
    retrieval.a_repo = FallbackAdminRepo()
    retrieval.vector = StubVector()
    retrieval.document_vector = FailingDocumentVector()
    retrieval._provider_for_tenant = lambda tenant_id: StubProvider()

    out = asyncio.run(
        retrieval.run(
            "tenant-1",
            "expense policy",
            knowledge_mode="glossary_documents",
            strict_glossary_mode=False,
        )
    )

    assert out["retrieval_degraded"] is True
    assert "document_vector_error" in out["retrieval_warnings"]
    assert out["top_documents"][0]["source"] == "upload_text"
