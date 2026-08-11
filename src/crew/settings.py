import os

USER_ID = "onlyone"
SESSION_ID = "111"


# EST-3285 4.2c: optional run-level token budget hard stop.
# Global fallback used when a session does not carry a per-run override
# (see GraphSessionManagerService.run_session / SessionData.initial_state
# reserved key "__token_budget__"). None (default) means "no limit" —
# the feature is fully inert unless TOKEN_BUDGET is set or a run explicitly
# opts in, so existing runs are byte-for-byte unchanged.
_raw_token_budget = os.environ.get("TOKEN_BUDGET")
DEFAULT_TOKEN_BUDGET: int | None = int(_raw_token_budget) if _raw_token_budget else None


AUDIT_TRAIL_ENABLED = os.environ.get("AUDIT_TRAIL_ENABLED", "False").lower() == "true"
AUDITOR_URL = os.environ.get("AUDITOR_URL", "http://auditor:8060")
AUDITOR_INGEST_API_KEY = os.environ.get("AUDITOR_INGEST_API_KEY", "")


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
