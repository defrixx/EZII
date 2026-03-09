import re
from typing import Any


PII_PATTERNS = [
    re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w{2,}\b"),
    re.compile(r"\b\+?\d[\d\s\-\(\)]{7,}\b"),
]


def redact_pii(text: str) -> str:
    redacted = text
    for pattern in PII_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {}
    for k, v in payload.items():
        if isinstance(v, str):
            sanitized[k] = redact_pii(v)
        else:
            sanitized[k] = v
    return sanitized
