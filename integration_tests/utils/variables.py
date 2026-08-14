import os

# DJANGO_URL = "http://django_app:8000/api"
# MANAGER_URL = "http://manager:8000"
rhost = "127.0.0.1"

DJANGO_URL = os.environ.get("DJANGO_URL", "http://127.0.0.1:8000/api")
MANAGER_URL = os.environ.get("MANAGER_URL", "http://127.0.0.1:8001")
TEST_TOOL_NAME = "PythonTestTool123"
DJANGO_ADMIN_EMAIL = os.environ.get("DJANGO_ADMIN_EMAIL", "admin@example.com")
DJANGO_ADMIN_PASSWORD = os.environ.get("DJANGO_ADMIN_PASSWORD", "AdminPass123!")

AUDITOR_URL = os.environ.get("AUDITOR_URL", "http://127.0.0.1:8060")
AUDITOR_INGEST_API_KEY = os.environ.get("AUDITOR_INGEST_API_KEY", "")

AUDIT_JWT_SECRET = os.environ.get("JWT_SECRET", "")

AUDIT_TEST_ORG_ID = os.environ.get("AUDIT_TEST_ORG_ID", "")

AUDIT_TOKEN_TTL_SECONDS = int(os.environ.get("AUDIT_TOKEN_TTL_SECONDS", "300"))
