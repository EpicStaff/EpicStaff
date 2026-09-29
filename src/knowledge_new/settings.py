from pathlib import Path

from src.shared.envtools import Env

BASE_DIR: Path = Path(__file__).resolve().parent

env = Env()

if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / "../.env")

DEBUG = env.bool("KNOWLEDGE_DEBUG")

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
