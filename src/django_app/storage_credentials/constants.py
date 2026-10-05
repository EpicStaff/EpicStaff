"""Constants for storage credentials."""

# Redis channel for code execution results.
CODE_RESULTS_CHANNEL = "code_results"

# `Secret(system=True, name=...)` that stores one organization's org-level
# storage IAM user credentials (access_key:secret_key, colon-joined plaintext).
SECRET_NAME_ORG_STORAGE_USER = "system_minio_org_user"

# Named storage policy attached to that same org-level user.
ORG_USER_POLICY_NAME_PREFIX = "org_storage_user_policy"
