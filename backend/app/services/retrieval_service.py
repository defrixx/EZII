import re
from dataclasses import dataclass


ALIASES = {"кафка": "kafka", "апи": "api"}
STOP_WORDS = {"что","это","как","такое","такая","такой","какие","какой","зачем","почему","ответь","кратко","для","при","или","the","what","how","why","which","with","from","this","that","about","please","briefly"}


def query_terms(value: str) -> list[str]:
    return [ALIASES.get(word, word) for word in re.findall(r"[^\W_]+", value.lower()) if len(word) > 2 and word not in STOP_WORDS]


@dataclass(frozen=True)
class RankedChunk:
    chunk: object
    score: float
    lexical_score: float
    vector_score: float | None


def hybrid_rank(query: str, chunks: list, vector_hits: list[dict] | None, limit: int = 8) -> list[RankedChunk]:
    """Fuse lexical and vector ranks, then rerank exact/phrase matches deterministically."""
    terms = query_terms(query)
    phrase = " ".join(terms)
    lexical: list[tuple[float, object]] = []
    for chunk in chunks:
        text = chunk.content.lower()
        occurrences = sum(text.count(term) for term in terms)
        coverage = sum(1 for term in set(terms) if term in text)
        phrase_bonus = 3 if phrase and phrase in text else 0
        score = float(occurrences + coverage * 2 + phrase_bonus)
        if score:
            lexical.append((score, chunk))
    lexical.sort(key=lambda item: (-item[0], str(item[1].id)))
    lexical_rank = {str(chunk.id): rank for rank, (_, chunk) in enumerate(lexical, 1)}
    lexical_value = {str(chunk.id): score for score, chunk in lexical}

    vector_hits = vector_hits or []
    vector_rank: dict[str, int] = {}
    vector_value: dict[str, float] = {}
    for rank, hit in enumerate(vector_hits, 1):
        chunk_id = str(hit.get("payload", {}).get("chunk_id", ""))
        if chunk_id and chunk_id not in vector_rank:
            vector_rank[chunk_id] = rank
            vector_value[chunk_id] = float(hit.get("score", 0))

    candidates = {str(chunk.id): chunk for chunk in chunks if str(chunk.id) in lexical_rank or str(chunk.id) in vector_rank}
    ranked: list[RankedChunk] = []
    max_lexical = max(lexical_value.values(), default=1)
    for chunk_id, chunk in candidates.items():
        rrf = (1 / (60 + lexical_rank[chunk_id]) if chunk_id in lexical_rank else 0) + (1 / (60 + vector_rank[chunk_id]) if chunk_id in vector_rank else 0)
        lexical_normalized = lexical_value.get(chunk_id, 0) / max_lexical
        vector_score = vector_value.get(chunk_id)
        combined = rrf * 20 + lexical_normalized * 0.55 + max(0, vector_score or 0) * 0.25
        ranked.append(RankedChunk(chunk, round(combined, 6), lexical_value.get(chunk_id, 0), vector_score))
    ranked.sort(key=lambda item: (-item.score, str(item.chunk.id)))
    return ranked[:limit]
