"""Storage credentials and scope contract for session, test-run, and realtime execution."""

from pydantic import BaseModel, ConfigDict


class StorageCredentials(BaseModel):
    """Temporary storage service account credentials.

    Issued per session/test-run/realtime, scoped to a union of `storage_allowed_paths`
    across all storage-demanding nodes in the execution. Never persisted — ephemeral
    payload only.
    """

    access_key: str
    """Temporary service account access key — unique identifier for the account."""

    secret_key: str
    """Temporary service account secret key — NOT logged."""

    model_config = ConfigDict(from_attributes=True)


class StorageScopedData(BaseModel):
    """Mixin for models that declare storage access requirements.

    Contains scope fields only — credentials are never embedded here. Scope fields
    describe what paths and org boundaries the execution is allowed to access.

    Intended for inheritance by PythonCodeData (graph node) and CodeTaskData (payload).
    """

    use_storage: bool = False
    """Whether this execution needs storage access. If true, credentials must be
    supplied via a sibling field on the containing model (e.g. CodeTaskData.storage_credentials,
    SessionData.storage_credentials), never embedded here.
    """

    storage_allowed_paths: list[str] | None = None
    """Paths within storage this execution is allowed to access.

    Union of all storage_allowed_paths across storage-demanding nodes in the session/task.
    Scoped by credential issuer to prevent org-wide access. None means unset (credential
    issuer will reject if use_storage=True and this is None).
    """

    storage_org_prefix: str | None = None
    """Organization prefix for storage isolation (e.g., 'org_123').

    Used to construct credential scope policy. Must be set if use_storage=True.
    """

    session_id: int | None = None
    """Session ID for audit and credential scoping. Null for test-run/realtime contexts."""

    org_id: int | None = None
    """Organization ID — required if use_storage=True."""

    model_config = ConfigDict(from_attributes=True)
