from tables.exceptions import CustomAPIExeption


class StorageCredentialError(CustomAPIExeption):
    """Base class for the storage_credentials domain."""

    status_code = 500
    default_detail = "Something went wrong with file storage access. Please try again."
    default_code = "storage_credential_error"


class StorageCredentialConfigError(StorageCredentialError):
    """STORAGE_ACCESS_KEY / STORAGE_SECRET_KEY / STORAGE_BUCKET_NAME missing
    from django_app's own environment. Raised fail-fast at process start,
    not surfaced per-request."""

    default_detail = "File storage isn't set up for this environment yet. Please contact support."
    default_code = "storage_credential_config_error"


class OrgStorageProvisioningError(StorageCredentialError):
    """Provisioning or deprovisioning an org-level storage user failed.

    Deliberately NOT caught inside `OrganizationManagementService.
    create_organization()`: an organization without storage provisioning is
    not a valid intermediate state, so the transaction rolls back the
    organization's creation entirely rather than leaving it half-provisioned.
    """

    default_detail = "We couldn't set up file storage for your organization. Please try again or contact support."
    default_code = "org_storage_provisioning_error"


class OrgStorageCredentialMissingError(StorageCredentialError):
    """No `Secret(system=True)` row exists for an organization that should
    already have been provisioned. Signals a provisioning/backfill gap, not
    a normal "not yet provisioned" state."""

    default_detail = "File storage isn't set up for your organization yet. Please contact support."
    default_code = "org_storage_credential_missing"


class CredentialScopeValidationError(StorageCredentialError):
    """The trusted scope for an execution_id is missing, malformed, or has
    `storage_allowed_paths` that escape `storage_org_prefix`. Raised before
    any MinIO API call."""

    status_code = 400
    default_detail = "This request doesn't specify which files it needs. Check the file attachments in your flow."
    default_code = "credential_scope_validation_error"


class TemporaryCredentialError(StorageCredentialError):
    """Base class for issuing/revoking one per-execution service account."""

    default_detail = "We couldn't complete the file storage request. Please try again."
    default_code = "temporary_credential_error"


class TemporaryCredentialIssueError(TemporaryCredentialError):
    """Minting a temporary service account failed."""

    default_detail = (
        "We couldn't grant access to file storage for this run. Please try again shortly."
    )
    default_code = "temporary_credential_issue_error"


class TemporaryCredentialRevokeError(TemporaryCredentialError):
    """Revoking a temporary service account failed. Callers should log this
    at ERROR and move on (best-effort revoke). Best-effort cleanup of
    orphaned accounts is provided by the manager's background cleanup job."""

    default_detail = (
        "We couldn't fully clean up temporary file storage access. This has been logged for review."
    )
    default_code = "temporary_credential_revoke_error"


class TemporaryCredentialListError(TemporaryCredentialError):
    """Listing an org's temporary service accounts failed."""

    default_detail = "We couldn't retrieve the list of active file storage sessions."
    default_code = "temporary_credential_list_error"
