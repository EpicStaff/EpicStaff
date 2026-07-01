import os

USER_ID = "onlyone"
SESSION_ID = "111"


COMMUNICATION_BROKER_BACKEND = "redis"
COMMUNICATION_BROKER_USER = os.getenv("COMUNICATION_BROKER_USER")
COMMUNICATION_BROKER_PASSWORD = os.getenv("COMUNICATION_BROKER_PASSWORD")
COMMUNICATION_BROKER_HOST = os.getenv("COMUNICATION_BROKER_HOST")
COMMUNICATION_BROKER_PORT = os.getenv("COMUNICATION_BROKER_PORT")
COMMUNICATION_BROKER_NAME = os.getenv("COMUNICATION_BROKER_NAME")

COMMUNICATION_STORAGE_BACKEND = "redis"
COMMUNICATION_STORAGE_USER = os.getenv("COMUNICATION_STORAGE_USER")
COMMUNICATION_STORAGE_PASSWORD = os.getenv("COMUNICATION_STORAGE_PASSWORD")
COMMUNICATION_STORAGE_HOST = os.getenv("COMUNICATION_STORAGE_HOST")
COMMUNICATION_STORAGE_PORT = os.getenv("COMUNICATION_STORAGE_PORT")
COMMUNICATION_STORAGE_NAME = os.getenv("COMUNICATION_STORAGE_NAME")

KNOWLEDGE_SEARCH_REQUEST_CHANNEL = os.getenv("KNOWLEDGE_SEARCH_REQUEST_CHANNEL")
KNOWLEDGE_SEARCH_RESPONSE_CHANNEL = os.getenv("KNOWLEDGE_SEARCH_RESPONSE_CHANNEL")


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
