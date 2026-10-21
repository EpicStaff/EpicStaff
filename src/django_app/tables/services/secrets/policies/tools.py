from tables.services.secrets.policies.base import SecretPolicy

MCP_TOOL_SECRET_POLICY = SecretPolicy(reference_fields=("auth_secret_id",))
PYTHON_CODE_SECRET_POLICY = SecretPolicy(reference_fields=("secret_ids",))
