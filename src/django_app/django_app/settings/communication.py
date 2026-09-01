from django_app.settings import env
from django_app.settings import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                {
                    "host": REDIS_HOST,
                    "port": REDIS_PORT,
                    "password": REDIS_PASSWORD,
                }
            ],
        },
    },
}

KNOWLEDGE_DOCUMENT_CHUNK_CHANNEL = env.str("KNOWLEDGE_DOCUMENT_CHUNK_CHANNEL", "knowledge:chunk")
KNOWLEDGE_DOCUMENT_CHUNK_RESPONSE = env.str("KNOWLEDGE_DOCUMENT_CHUNK_RESPONSE", "knowledge:chunk:response")
KNOWLEDGE_INDEXING_CHANNEL = env.str("KNOWLEDGE_INDEXING_CHANNEL", "knowledge:indexing")

STOP_SESSION_CHANNEL = env.str("STOP_SESSION_CHANNEL", "sessions:stop")

REQUEST_WEBHOOK_UPDATE_CHANNEL = env.str("REQUEST_WEBHOOK_UPDATE_CHANNEL", "REQUEST_WEBHOOK_UPDATE_CHANNEL")

SESSION_STATUS_CHANNEL = env.str("SESSION_STATUS_CHANNEL", "sessions:session_status")

CODE_RESULT_CHANNEL = env.str("CODE_RESULT_CHANNEL", "code_results")

GRAPH_MESSAGES_CHANNEL = env.str("GRAPH_MESSAGES_CHANNEL", "graph:messages")
GRAPH_MESSAGE_UPDATE_CHANNEL = env.str("GRAPH_MESSAGE_UPDATE_CHANNEL", "graph:message:update")

WEBHOOK_MESSAGE_CHANNEL = env.str("WEBHOOK_MESSAGE_CHANNEL", "webhooks")

STORAGE_MUTATION_CHANNEL = env.str("STORAGE_MUTATION_CHANNEL", "storage_mutations")

SCHEDULE_CHANNEL = env.str("SCHEDULE_CHANNEL", "schedule_channel")
SCHEDULE_MIN_INTERVAL_SECONDS = env.int("SCHEDULE_MIN_INTERVAL_SECONDS", 60)
SCHEDULE_MAX_CONCURRENT_SESSIONS_PER_ORG = env.int("SCHEDULE_MAX_CONCURRENT_SESSIONS_PER_ORG", 20)