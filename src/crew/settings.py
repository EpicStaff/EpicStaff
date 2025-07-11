import os

USER_ID = "onlyone"
SESSION_ID = "111"


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
