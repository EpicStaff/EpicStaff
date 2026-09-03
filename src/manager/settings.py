from pathlib import Path

from src.shared.envtools import Env


BASE_DIR = Path(__file__).resolve().parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / '../.env')

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")

SESSION_SCHEMA_CHANNEL = env.str("SESSION_SCHEMA_CHANNEL")
SESSION_TIMEOUT_CHANNEL = env.str("SESSION_TIMEOUT_CHANNEL")

DB_USER = env.str("MANAGER_DB_USER")
DB_PASSWORD = env.str("MANAGER_DB_PASSWORD")
DB_PORT = env.str("DB_PORT")
DB_HOST = env.str("DB_HOST")
DB_NAME = env.str("DB_NAME")

SCHEDULE_CHANNEL = env.str("SCHEDULE_CHANNEL")
TIMEZONE = env.str("DJANGO_TIMEZONE", "UTC")
SYNC_RETRY_DELAY = 5
