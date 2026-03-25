import re
from typing import Any


PII_PATTERNS = [
    re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w{2,}\b"),
    re.compile(r"\b\+?\d[\d\s\-\(\)]{7,}\b"),
]
SENSITIVE_PATTERNS = [
    re.compile(r"\bauthorization\s*:\s*[^\n\r]*", flags=re.IGNORECASE),
    # JWT / bearer / API tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b(?:bearer|token|api[_-]?key|secret|password)\s*[:=]\s*[^\s,;]{8,}\b", flags=re.IGNORECASE),
    # PEM/private key fragments
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", flags=re.DOTALL),
]
SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "api_key",
    "secret",
    "password",
    "client_secret",
    "cookie",
    "set-cookie",
}


def redact_pii(text: str) -> str:
    redacted = text
    for pattern in PII_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def sanitize_text_for_logs(text: str, max_len: int = 512) -> str:
    cleaned = redact_pii(str(text))
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[:max_len].rstrip()}..."


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def _sanitize(value: Any, key_hint: str | None = None) -> Any:
        if isinstance(value, str):
            if (key_hint or "").strip().lower() in SENSITIVE_KEYS:
                return "[REDACTED]"
            return sanitize_text_for_logs(value)
        if isinstance(value, dict):
            return {
                str(k): _sanitize(v, str(k))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_sanitize(item, key_hint) for item in value]
        if isinstance(value, tuple):
            return tuple(_sanitize(item, key_hint) for item in value)
        return value

    sanitized = {}
    for k, v in payload.items():
        sanitized[k] = _sanitize(v, k)
    return sanitized
