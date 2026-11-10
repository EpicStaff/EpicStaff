from src.shared.models import SessionData
from src.shared.models.storage_scope import StorageCredentials, StorageGrant


def pick_storage_credentials(
    grant: StorageGrant | None,
    default: StorageCredentials | None,
    by_grant: dict[str, StorageCredentials],
) -> StorageCredentials | None:
    """The account a piece of code runs with: its grant's, else the session's default.

    Django mints an account per storage grant only for an unattended run. Code with no
    grant, a grant nothing was minted for, or any code of an attended run (where
    `by_grant` is empty) gets the default account, which is how every run behaved
    before grants existed.
    """
    if grant is not None and grant.key in by_grant:
        return by_grant[grant.key]
    return default


def storage_credentials_for(
    session_data: SessionData, grant: StorageGrant | None
) -> StorageCredentials | None:
    """`pick_storage_credentials` over the accounts of `session_data`."""
    return pick_storage_credentials(
        grant, session_data.storage_credentials, session_data.storage_credentials_by_grant
    )
