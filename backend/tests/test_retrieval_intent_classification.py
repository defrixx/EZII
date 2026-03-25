from app.services.retrieval_service import RetrievalService


def test_detect_intent_exact_term_has_priority():
    intent = RetrievalService._detect_intent("any query", exact_count=1, glossary_count=1)
    assert intent == "exact_term"


def test_detect_intent_composite_for_compare_signal():
    intent = RetrievalService._detect_intent("compare approach a and approach b", exact_count=0, glossary_count=1)
    assert intent == "composite"


def test_detect_intent_not_composite_for_plain_and_or_words():
    intent_and = RetrievalService._detect_intent("explain term a and term b", exact_count=0, glossary_count=1)
    intent_or = RetrievalService._detect_intent("explain term a or term b", exact_count=0, glossary_count=1)
    assert intent_and == "semantic_lookup"
    assert intent_or == "semantic_lookup"


def test_detect_intent_web_assisted_when_no_hits():
    intent = RetrievalService._detect_intent("rare topic", exact_count=0, glossary_count=0)
    assert intent == "web_assisted"


def test_detect_intent_list_query_for_top_signal():
    intent = RetrievalService._detect_intent("top 10 owasp llm vulnerabilities", exact_count=0, glossary_count=1)
    assert intent == "list_query"


def test_extract_requested_list_size_for_russian_list_phrase():
    size = RetrievalService._extract_requested_list_size("дай 12 уязвимостей owasp для llm")
    assert size == 12
