from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    app_name:str="EZII Knowledge"
    database_url:str="postgresql+psycopg2://app:app@postgres:5432/app"
    qdrant_url:str="http://qdrant:6333"
    document_storage_path:str="/app/data/documents"
    document_upload_max_bytes:int=52_428_800
    website_snapshot_max_bytes:int=10_485_760
    document_chunk_size_chars:int=900
    document_chunk_overlap_chars:int=250
    provider_api_key_encryption_key:str=""
    local_model_hosts:str="host.docker.internal,localhost,127.0.0.1,::1"

@lru_cache
def get_settings(): return Settings()
