from tables.exceptions import CustomAPIExeption


class StorageCredentialError(CustomAPIExeption):
    """Base class for the storage_credentials domain."""

    status_code = 500
    default_detail = "Storage credential operation failed."
    default_code = "storage_credential_error"


class StorageCredentialConfigError(StorageCredentialError):
    """STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY / STORAGE_BUCKET_NAME missing
    from django_app's own environment. Raised fail-fast at process start,
    not surfaced per-request."""

    default_detail = "Storage credential configuration is missing."
    default_code = "storage_credential_config_error"


class OrgStorageProvisioningError(StorageCredentialError):
    """Provisioning or deprovisioning an org-level MinIO user failed.

    Deliberately NOT caught inside `OrganizationManagementService.
    create_organization()`: an organization without storage provisioning is
    not a valid intermediate state, so the transaction rolls back the
    organization's creation entirely rather than leaving it half-provisioned.
    """

    default_detail = "Failed to provision or deprovision org-level storage."
    default_code = "org_storage_provisioning_error"


class OrgStorageCredentialMissingError(StorageCredentialError):
    """No `Secret(system=True)` row exists for an organization that should
    already have been provisioned. Signals a provisioning/backfill gap, not
    a normal "not yet provisioned" state."""

    default_detail = "Org-level storage credential is missing."
    default_code = "org_storage_credential_missing"


class CredentialScopeValidationError(StorageCredentialError):
    """The trusted scope for an execution_id is missing, malformed, or has
    `storage_allowed_paths` that escape `storage_org_prefix`. Raised before
    any MinIO API call."""

    status_code = 400
    default_detail = "Storage credential scope is invalid."
    default_code = "credential_scope_validation_error"


class TemporaryCredentialError(StorageCredentialError):
    """Base class for issuing/revoking one per-execution service account."""

    default_detail = "Temporary storage credential operation failed."
    default_code = "temporary_credential_error"


class TemporaryCredentialIssueError(TemporaryCredentialError):
    """Minting a temporary service account failed."""

    default_detail = "Failed to mint temporary storage credential."
    default_code = "temporary_credential_issue_error"


class TemporaryCredentialRevokeError(TemporaryCredentialError):
    """Revoking a temporary service account failed. Callers should log this
    at ERROR and move on -- an un-revoked account is picked up by
    `TtlReconciliationService.sweep()` once it expires."""

    default_detail = "Failed to revoke temporary storage credential."
    default_code = "temporary_credential_revoke_error"
