from pathlib import Path

from src.shared.envtools import Env

BASE_DIR: Path = Path(__file__).resolve().parent

env = Env()

if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / "../.env")

DEBUG = env.bool("KNOWLEDGE_DEBUG")

LOG_LEVEL = env.log_level("KNOWLEDGE_LOG_LEVEL", "INFO")

MAX_PROCESS_WORKERS = env.int("KNOWLEDGE_MAX_PROCESS_WORKERS")

DATABASE_DNS = env.dns(
    "postgresql+psycopg",
    "DB_HOST",
    "DB_PORT",
    "KNOWLEDGE_DB_USER",
    "KNOWLEDGE_DB_PASSWORD",
    "DB_NAME",
)

STORAGE_ENDPOINT = (
    f"{'https' if env.bool('STORAGE_SSL') else 'http'}://"
    f"{env.str('STORAGE_HOST')}:{env.int('STORAGE_PORT')}"
)
STORAGE_ACCESS_KEY = env.str("STORAGE_USER")
STORAGE_SECRET_KEY = env.str("STORAGE_PASSWORD")
KNOWLEDGE_BUCKET = env.str("KNOWLEDGE_STORAGE_BUCKET")

GRAPHRAG_ENCODING = "utf-8"

# Deployment-wide overrides for the embedding endpoint. Unset in every standard
# install; set only where embeddings are routed through an API gateway.
CUSTOM_EMBED_BASE_URL = env.str("KNOWLEDGE_CUSTOM_EMBED_BASE_URL", None)
EMBEDDING_HEADERS = env.dict("KNOWLEDGE_EMBEDDING_HEADERS", None)
