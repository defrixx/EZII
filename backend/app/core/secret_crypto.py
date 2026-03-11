from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


ENC_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    raw = (get_settings().provider_api_key_encryption_key or "").strip()
    if not raw:
        raise RuntimeError("PROVIDER_API_KEY_ENCRYPTION_KEY is not configured")
    return Fernet(raw.encode("utf-8"))


def encrypt_secret(value: str) -> str:
    if not value:
        return value
    if value.startswith(ENC_PREFIX):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENC_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    if not value:
        return value
    if not value.startswith(ENC_PREFIX):
        return value
    token = value[len(ENC_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Stored provider API key cannot be decrypted") from exc
