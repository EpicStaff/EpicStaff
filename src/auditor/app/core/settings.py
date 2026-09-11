import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, Any


config_dict: Dict[str, Any] = {"env_file_encoding": "utf-8", "extra": "ignore"}


class Settings(BaseSettings):
    PROJECT_NAME: str = "auditor"
    DESCRIPTION: str = "EpicStaff audit trail service"
    VERSION: str = "0.1.0"

    AUDITOR_DEBUG: bool = False
    AUDITOR_PORT: int = 8060
    LOG_LEVEL: str = "INFO"

    AUDIT_STORAGE_BACKEND: str = "opensearch"

    OPENSEARCH_HOST: str = "opensearch"
    OPENSEARCH_PORT: int = 9200
    OPENSEARCH_USER: str = "admin"
    OPENSEARCH_PASSWORD: str

    AUDITOR_INGEST_API_KEY: str
    JWT_SECRET: str
    CORS_ALLOWED_ORIGINS: str = "http://localhost:4200"

    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str
    AUDITOR_REDIS_DB: int

    EXPORT_DATA_DIR: str = "/app/export_data"
    EXPORT_FILE_TTL_SECONDS: int = 60 * 60 * 24

    model_config = SettingsConfigDict(**config_dict)


try:
    settings = Settings()
except (ValueError, FileNotFoundError) as e:
    print(f"\nFATAL CONFIGURATION ERROR:\n{e}", file=sys.stderr)
    sys.exit(1)
