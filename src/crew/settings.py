import os
from pathlib import Path

from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / '../.env')

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")

DB_USER = env.str("CREW_DB_USER")
DB_PASSWORD = env.str("CREW_DB_PASSWORD")
DB_PORT = env.int("DB_PORT")
DB_HOST = env.str("DB_HOST")
DB_NAME = env.str("DB_NAME")

LLM_HEADERS = env.str("CREW_LLM_HEADERS")
REMEMBERED_OUTPUTS_TTL = env.time("CREW_REMEMBERED_OUTPUTS_TTL")

KNOWLEDGE_SEARCH_REQUEST_CHANNEL = env.str("KNOWLEDGE_SEARCH_REQUEST_CHANNEL")
KNOWLEDGE_SEARCH_RESPONSE_CHANNEL = env.str("KNOWLEDGE_SEARCH_RESPONSE_CHANNEL")
SESSION_STATUS_CHANNEL = env.str("SESSION_STATUS_CHANNEL")
SESSION_SCHEMA_CHANNEL = env.str("SESSION_SCHEMA_CHANNEL")
SESSION_TIMEOUT_CHANNEL = env.str("SESSION_TIMEOUT_CHANNEL")
MAX_CONCURRENT_SESSIONS = env.int("CREW_MAX_CONCURRENT_SESSIONS")
CODE_EXEC_CHANNEL = env.str("CODE_EXEC_CHANNEL")
CODE_RESULT_CHUNNEL = env.str("CODE_RESULT_CHANNEL")

CREWAI_OUTPUT_CHANNEL = env.str("CREWAI_OUTPUT_CHANNEL")
STOP_SESSION_CHANNEL = env.str("STOP_SESSION_CHANNEL")
MEMORY_UPDATE_CHANNEL = env.str("MEMORY_UPDATE_CHANNEL")

AGENT_REQUEST_STREAM = env.str("AGENT_REQUEST_STREAM")
AGENT_RESULT_STREAM = env.str("AGENT_RESULT_STREAM")
AGENT_RESULT_TIMEOUT = env.time("AGENT_RESULT_TIMEOUT")

DEFAULT_RAG_SEARCH_TIMEOUT = env.time("DEFAULT_RAG_SEARCH_TIMEOUT")
NAIVE_RAG_SEARCH_TIMEOUT = env.time("NAIVE_RAG_SEARCH_TIMEOUT")
GRAPH_RAG_SEARCH_TIMEOUT = env.time("GRAPH_RAG_SEARCH_TIMEOUT")

# EST-3285 4.2c: optional run-level token budget hard stop.
# Global fallback used when a session does not carry a per-run override
# (see GraphSessionManagerService.run_session / SessionData.initial_state
# reserved key "__token_budget__"). None (default) means "no limit" —
# the feature is fully inert unless TOKEN_BUDGET is set or a run explicitly
# opts in, so existing runs are byte-for-byte unchanged.
DEFAULT_TOKEN_BUDGET = env.int("TOKEN_BUDGET") or None

USER_ID = "onlyone"
SESSION_ID = "111"

PGVECTOR_MEMORY_CONFIG = {
    "provider": "local_mem0",
    "config": {"user_id": USER_ID, "run_id": SESSION_ID},
    "config_dict": {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "collection_name": "tables_memorydatabase",
                "user": DB_USER,
                "password": DB_PASSWORD,
                "port": DB_PORT,
                "host": DB_HOST,
                "dbname": DB_NAME,
            },
        },
        "redis": {
            "host": REDIS_HOST,
            "port": REDIS_PORT,
            "db": 0,
            "channel": MEMORY_UPDATE_CHANNEL,
        },
    },
}
