"""Storage credentials and scope contract for session, test-run, and realtime execution."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StorageAction(StrEnum):
    """What a run's code may do to the files attached to it (outside its own folders).

    Derived by django from the acting identity's FILES permissions: READ needs
    FILES:READ; WRITE needs READ plus both FILES:CREATE and FILES:UPDATE, because
    storage cannot tell creating an object from overwriting one; DELETE needs READ
    plus FILES:DELETE.
    """

    READ = "read"
    WRITE = "write"
    DELETE = "delete"


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

    shared_actions: list[StorageAction] | None = None
    """Actions the account allows on the allowed paths outside `own_paths`.

    Mirrors the acting identity's permissions so `epicstaff_storage` can refuse an
    operation before calling storage. An organization with no storage left additionally
    gets an account without write access, which `free_bytes` and `purgeable_bytes`
    report instead. None means the issuer did not narrow them, and the library keeps its
    path-only checks.
    """

    own_paths: list[str] = Field(default_factory=list)
    """The run's own folders (`sessions/<id>/`, `test-runs/...`): every action allowed."""

    free_bytes: int | None = None
    """Bytes the organization may still add to storage when the account was issued.

    `epicstaff_storage` refuses a write past it unless the oldest recycle-bin items may be
    purged to make room. None means no limit is known and nothing is checked.
    """

    purgeable_bytes: int | None = None
    """Bytes beyond `free_bytes` that purging the organization's recycle bin would free.

    Only non-zero when the identity the run acts as may purge the bin; zero otherwise.
    None means no limit is known.
    """

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
