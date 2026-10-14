import os

# app.core.settings requires these at import time (no defaults); dummy values mirror what
# docker-compose injects, so the suite runs without a real .env file.
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("AUDIT_JWT_SECRET", "test-secret-long-enough-for-hs256-keys")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_USER", "test")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")
