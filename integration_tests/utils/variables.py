import os

# DJANGO_URL = "http://django_app:8000/api"
# MANAGER_URL = "http://manager:8000"
rhost = "127.0.0.1"

DJANGO_URL = os.environ.get("DJANGO_URL", "http://127.0.0.1:8000/api")
MANAGER_URL = os.environ.get("MANAGER_URL", "http://127.0.0.1:8001")
TEST_TOOL_NAME = "PythonTestTool123"
DJANGO_ADMIN_EMAIL = os.environ.get("DJANGO_ADMIN_EMAIL", "admin@example.com")
DJANGO_ADMIN_PASSWORD = os.environ.get("DJANGO_ADMIN_PASSWORD", "AdminPass123!")
