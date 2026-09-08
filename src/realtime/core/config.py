import sys
from pathlib import Path

from src.shared import humanize
from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parent.parent

_is_debug = "--debug" in sys.argv

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / '../.env')

HOST = env.str("REALTIME_HOST")
REALTIME_PORT = env.int("REALTIME_PORT")
REALTIME_WORKERS = env.int("REALTIME_SGI_WORKERS")

REALTIME_DEBUG_MODE: bool = _is_debug
REALTIME_RELOAD: bool = _is_debug

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")

KNOWLEDGE_SEARCH_GET_CHANNEL = env.str("KNOWLEDGE_SEARCH_REQUEST_CHANNEL")
KNOWLEDGE_SEARCH_RESPONSE_CHANNEL = env.str("KNOWLEDGE_SEARCH_RESPONSE_CHANNEL")
REALTIME_AGENTS_SCHEMA_CHANNEL = env.str("REALTIME_AGENTS_SCHEMA_CHANNEL")

CONNECTION_KEY_TTL_SECONDS = humanize.to_time("5m")
STREAM_TOKEN_TTL_SECONDS = humanize.to_time("2m")
MAX_CALL_DURATION_SECONDS = humanize.to_time("30m")

DJANGO_HOST = env.str("DJANGO_HOST")
DJANGO_PORT = env.int("DJANGO_PORT")
DJANGO_AUTH_URL = env.str("DJANGO_AUTH_URL")
DJANGO_API_KEY = env.str("DJANGO_API_KEY")
DJANGO_AUTH_TIMEOUT = env.time("DJANGO_AUTH_TIMEOUT")
DJANGO_CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS")

DB_HOST_NAME = env.str("DB_HOST")
DB_PORT = env.int("DB_PORT")
DB_NAME = env.str("DB_NAME")
DB_USER = env.str("REALTIME_DB_USER")
DB_PASSWORD = env.str("REALTIME_DB_PASSWORD")

TWILIO_ACCOUNT_SID = env.str("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env.str("TWILIO_AUTH_TOKEN")
TWILIO_VOICE_AGENT_ID = env.str("TWILIO_VOICE_AGENT_ID")
VOICE_STREAM_URL = env.str("TWILIO_VOICE_STREAM_URL")

DJANGO_API_BASE_URL = f"http://{DJANGO_HOST}:{DJANGO_PORT}/api"

INIT_API_URL = f"{DJANGO_API_BASE_URL}/init-realtime/"

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST_NAME}:{DB_PORT}/{DB_NAME}"
