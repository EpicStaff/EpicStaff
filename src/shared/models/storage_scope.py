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


class StorageGrant(BaseModel):
    """What one code-running node may do to the files attached to its flow in an unattended run.

    Set per node (or per code slot of a node) by whoever configured the flow. A run
    with no identity of its own (schedule, webhook and Telegram triggers) gets
    exactly these actions on the attached files; a node with no grant (None) keeps
    the run's default access.
    """

    read: bool = False
    write: bool = False
    delete: bool = False

    model_config = ConfigDict(frozen=True)

    @property
    def actions(self) -> frozenset[StorageAction]:
        """The actions this grant allows."""
        return frozenset(
            action
            for action, allowed in (
                (StorageAction.READ, self.read),
                (StorageAction.WRITE, self.write),
                (StorageAction.DELETE, self.delete),
            )
            if allowed
        )

    @property
    def key(self) -> str:
        """Stable identifier of the combination, the same wherever it is computed.

        One letter per allowed action in the fixed order read, write, delete, `-` for a
        missing one: "r-d" is read and delete, "---" is none.
        """
        return "".join(
            letter if allowed else "-"
            for letter, allowed in (("r", self.read), ("w", self.write), ("d", self.delete))
        )

    @classmethod
    def from_key(cls, key: str) -> "StorageGrant":
        """The grant a `key` names."""
        return cls(read=key[0] == "r", write=key[1] == "w", delete=key[2] == "d")


# What File Extractor and Audio to Text nodes run with: they carry no grant of their own
# and only read the flow's attached files.
FILE_NODE_STORAGE_GRANT = StorageGrant(read=True)


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
    operation before calling storage. None means the issuer did not narrow them, and the
    library keeps its path-only checks.
    """

    own_paths: list[str] = Field(default_factory=list)
    """The run's own folders (`sessions/<id>/`, `test-runs/...`): every action allowed."""

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

    storage_grant: StorageGrant | None = None
    """The grant of the node or code slot that owns this code; None when it has none.

    Picks which of the session's temporary accounts this code runs with (see
    `SessionData.storage_credentials_by_grant`).
    """

    model_config = ConfigDict(from_attributes=True)
