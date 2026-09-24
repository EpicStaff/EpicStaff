from pathlib import Path

from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parents[2]

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / "../.env")


PROJECT_NAME = env.str("PROJECT_NAME", "auditor")
DESCRIPTION = env.str("DESCRIPTION", "EpicStaff audit trail service")
VERSION = env.str("VERSION", "0.1.0")

AUDITOR_DEBUG = env.bool("AUDITOR_DEBUG", False)
AUDITOR_PORT = env.int("AUDITOR_PORT", 8060)
AUDITOR_LOG_LEVEL = env.str("AUDITOR_LOG_LEVEL", "INFO")

AUDITOR_EXPORT_DATA_DIR = env.str("AUDITOR_EXPORT_DATA_DIR", "/app/export_data")
AUDITOR_EXPORT_FILE_TTL_SECONDS = env.int("AUDITOR_EXPORT_FILE_TTL_SECONDS", 60 * 60 * 24)
AUDITOR_EXPORT_MAX_ROWS = env.int("AUDITOR_EXPORT_MAX_ROWS", 100_000)

AUDIT_STORAGE_BACKEND = env.str("AUDIT_STORAGE_BACKEND", "opensearch")

OPENSEARCH_HOST = env.str("OPENSEARCH_HOST", "opensearch")
OPENSEARCH_PORT = env.int("OPENSEARCH_PORT", 9200)
OPENSEARCH_USER = env.str("OPENSEARCH_USER", "admin")
OPENSEARCH_PASSWORD = env.str("OPENSEARCH_PASSWORD")

AUDITOR_INGEST_API_KEY = env.str("AUDITOR_INGEST_API_KEY")
JWT_SECRET = env.str("JWT_SECRET")
CORS_ALLOWED_ORIGINS = env.str("CORS_ALLOWED_ORIGINS", "http://localhost:4200")

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")
AUDITOR_REDIS_DB = env.int("AUDITOR_REDIS_DB")
