class StorageCredentialError(Exception):
    """Base class for the storage_credentials domain."""


class StorageCredentialConfigError(StorageCredentialError):
    """STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY / STORAGE_BUCKET_NAME missing
    from django_app's own environment. Raised fail-fast at process start,
    not surfaced per-request."""


class OrgStorageProvisioningError(StorageCredentialError):
    """Provisioning or deprovisioning an org-level MinIO user failed.

    Deliberately NOT caught inside `OrganizationManagementService.
    create_organization()`: an organization without storage provisioning is
    not a valid intermediate state, so the transaction rolls back the
    organization's creation entirely rather than leaving it half-provisioned.
    """


class OrgStorageCredentialMissingError(StorageCredentialError):
    """No `Secret(system=True)` row exists for an organization that should
    already have been provisioned. Signals a provisioning/backfill gap, not
    a normal "not yet provisioned" state."""


class CredentialScopeValidationError(StorageCredentialError):
    """The trusted scope for an execution_id is missing, malformed, or has
    `storage_allowed_paths` that escape `storage_org_prefix`. Raised before
    any MinIO API call."""


class TemporaryCredentialError(StorageCredentialError):
    """Base class for issuing/revoking one per-execution service account."""


class TemporaryCredentialIssueError(TemporaryCredentialError):
    """Minting a temporary service account failed.

    `transient` distinguishes errors worth a caller-side retry (e.g. a
    momentary MinIO connectivity blip) from ones that are not (e.g. a
    rejected policy) -- callers may use it to decide whether to retry.
    """

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class TemporaryCredentialRevokeError(TemporaryCredentialError):
    """Revoking a temporary service account failed. Callers should log this
    at ERROR and move on -- an un-revoked account is picked up by
    `TtlReconciliationService.sweep()` once it expires."""
