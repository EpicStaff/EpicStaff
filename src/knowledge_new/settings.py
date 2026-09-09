from pathlib import Path

from src.shared.envtools import Env

BASE_DIR: Path = Path(__file__).resolve().parent

env = Env()

if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / '../.env')

DEBUG = env.bool("KNOWLEDGE_DEBUG")

MAX_PROCESS_WORKERS = env.int("KNOWLEDGE_MAX_PROCESS_WORKERS")

DATABASE_DNS = env.dns(
    "postgresql+psycopg",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "KNOWLEDGE_DB_BACKEND",
    "KNOWLEDGE_DB_USER",
)

MINIO_HOST = env.str("MINIO_HOST")
MINIO_ACCESS_KEY = env.str("MINIO_USER")
MINIO_SECRET_KEY = env.str("MINIO_PASSWORD")
MINIO_BUCKET = env.str("KNOWLEDGE_MINIO_BUCKET")

GRAPHRAG_ENCODING = "utf-8"
