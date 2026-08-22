import os

USER_ID = "onlyone"
SESSION_ID = "111"


COMMUNICATION_BROKER_BACKEND = "redis"
COMMUNICATION_BROKER_USER = os.getenv("COMMUNICATION_BROKER_USER")
COMMUNICATION_BROKER_PASSWORD = os.getenv("COMMUNICATION_BROKER_PASSWORD")
COMMUNICATION_BROKER_HOST = os.getenv("COMMUNICATION_BROKER_HOST")
COMMUNICATION_BROKER_PORT = os.getenv("COMMUNICATION_BROKER_PORT")
COMMUNICATION_BROKER_NAME = os.getenv("COMMUNICATION_BROKER_NAME")

COMMUNICATION_STORAGE_BACKEND = "redis"
COMMUNICATION_STORAGE_USER = os.getenv("COMMUNICATION_STORAGE_USER")
COMMUNICATION_STORAGE_PASSWORD = os.getenv("COMMUNICATION_STORAGE_PASSWORD")
COMMUNICATION_STORAGE_HOST = os.getenv("COMMUNICATION_STORAGE_HOST")
COMMUNICATION_STORAGE_PORT = os.getenv("COMMUNICATION_STORAGE_PORT")
COMMUNICATION_STORAGE_NAME = os.getenv("COMMUNICATION_STORAGE_NAME")

KNOWLEDGE_SEARCH_REQUEST_CHANNEL = os.getenv("KNOWLEDGE_SEARCH_REQUEST_CHANNEL")
KNOWLEDGE_SEARCH_RESPONSE_CHANNEL = os.getenv("KNOWLEDGE_SEARCH_RESPONSE_CHANNEL")


# EST-3285 4.2c: optional run-level token budget hard stop.
# Global fallback used when a session does not carry a per-run override
# (see GraphSessionManagerService.run_session / SessionData.initial_state
# reserved key "__token_budget__"). None (default) means "no limit" —
# the feature is fully inert unless TOKEN_BUDGET is set or a run explicitly
# opts in, so existing runs are byte-for-byte unchanged.
_raw_token_budget = os.environ.get("TOKEN_BUDGET")
DEFAULT_TOKEN_BUDGET: int | None = int(_raw_token_budget) if _raw_token_budget else None


PGVECTOR_MEMORY_CONFIG = {
    "provider": "local_mem0",
    "config": {"user_id": USER_ID, "run_id": SESSION_ID},
    "config_dict": {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "user": os.environ.get("DB_CREW_USER", "postgres"),
                "password": os.environ.get("DB_CREW_PASSWORD", "admin"),
                "port": os.environ.get("DB_PORT", "5432"),
                "collection_name": "tables_memorydatabase",
                "host": os.environ.get("DB_HOST_NAME", None),
                "dbname": os.environ.get("DB_NAME", "crew"),
            },
        },
        "redis": {
            "host": os.environ.get("REDIS_HOST", "127.0.0.1"),
            "port": int(os.environ.get("REDIS_PORT", 6379)),
            "db": 0,
            "channel": "memory:update",
        },
    },
}
