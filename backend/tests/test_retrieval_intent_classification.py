from app.services.retrieval_service import RetrievalService


def test_detect_intent_exact_term_has_priority():
    intent = RetrievalService._detect_intent("любой запрос", exact_count=1, glossary_count=1)
    assert intent == "exact_term"


def test_detect_intent_composite_for_compare_signal():
    intent = RetrievalService._detect_intent("сравни подход а и подход б", exact_count=0, glossary_count=1)
    assert intent == "composite"


def test_detect_intent_not_composite_for_plain_and_or_words():
    intent_and = RetrievalService._detect_intent("объясни термин а и термин б", exact_count=0, glossary_count=1)
    intent_or = RetrievalService._detect_intent("объясни термин а или термин б", exact_count=0, glossary_count=1)
    assert intent_and == "semantic_lookup"
    assert intent_or == "semantic_lookup"


def test_detect_intent_web_assisted_when_no_hits():
    intent = RetrievalService._detect_intent("редкая тема", exact_count=0, glossary_count=0)
    assert intent == "web_assisted"
