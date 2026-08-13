import os

# DJANGO_URL = "http://django_app:8000/api"
# MANAGER_URL = "http://manager:8000"
rhost = "127.0.0.1"

DJANGO_URL = os.environ.get("DJANGO_URL", "http://127.0.0.1:8000/api")
MANAGER_URL = os.environ.get("MANAGER_URL", "http://127.0.0.1:8001")
TEST_TOOL_NAME = "PythonTestTool123"
DJANGO_ADMIN_EMAIL = os.environ.get("DJANGO_ADMIN_EMAIL", "admin@example.com")
DJANGO_ADMIN_PASSWORD = os.environ.get("DJANGO_ADMIN_PASSWORD", "AdminPass123!")

# EST-3322 audit trail. The audit stack is gated behind the `audit` compose
# profile, so these tests skip rather than fail when it isn't running.
AUDITOR_URL = os.environ.get("AUDITOR_URL", "http://127.0.0.1:8060")
AUDITOR_INGEST_API_KEY = os.environ.get("AUDITOR_INGEST_API_KEY", "")
# Same secret django_app signs audit tokens with and auditor verifies them
# against - named distinctly here to keep it clear this is the cross-service
# audit secret, not this suite's own Django login credential.
AUDIT_JWT_SECRET = os.environ.get("JWT_SECRET", "")
# Optional pin; when unset the first organization from the admin listing is used.
AUDIT_TEST_ORG_ID = os.environ.get("AUDIT_TEST_ORG_ID", "")
