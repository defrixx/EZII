from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EZII API"
    app_env: str = "production"
    debug: bool = False

    database_url: str = "postgresql+psycopg2://app:app@postgres:5432/app"
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "glossary_entries"

    keycloak_server_url: str = "http://keycloak:8080"
    keycloak_issuer: str = "http://localhost:8080"
    keycloak_realm: str = "ezii"
    keycloak_audience: str = "assistant-api"
    keycloak_jwks_ttl_s: int = 300
    keycloak_admin_realm: str = "master"
    keycloak_admin_client_id: str = "admin-cli"
    keycloak_admin: str = ""
    keycloak_admin_password: str = ""
    default_tenant_id: str = ""
    register_require_email_verification: bool = True
    register_requires_admin_approval: bool = False
    register_enforce_captcha: bool = False
    register_captcha_provider: str = "builtin"
    register_builtin_captcha_ttl_s: int = 180
    turnstile_secret_key: str = ""
    hcaptcha_secret_key: str = ""
    oidc_frontend_client_id: str = "ezii-frontend"
    oidc_frontend_redirect_uri: str = "http://localhost/auth/callback"

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_embedding_model: str = "text-embedding-3-small"
    provider_timeout_s: int = 30
    provider_max_retries: int = 2

    rate_limit_per_minute: int = 60
    register_rate_limit_per_ip_per_hour: int = 20
    register_rate_limit_per_email_per_hour: int = 10
    rate_limit_fail_open: bool = False
    cors_origins: str = "http://localhost,http://127.0.0.1"
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = "lax"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
