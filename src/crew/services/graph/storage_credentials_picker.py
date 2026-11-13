from src.shared.models import SessionData
from src.shared.models.storage_scope import StorageCredentials, StorageGrant, storage_account_key


def pick_storage_credentials(
    grant: StorageGrant | None,
    graph_id: int | None,
    default: StorageCredentials | None,
    by_grant: dict[str, StorageCredentials],
) -> StorageCredentials | None:
    """The account a piece of code runs with: its grant's in its own flow, else the default.

    Django mints one account per grant and flow, and a flow's account reaches only that
    flow's attached files. Only code with no grant at all (an agent's python tool) takes
    the session's default account. Code whose grant has no account gets none, rather
    than falling back to wider access.
    """
    if grant is None:
        return default
    return by_grant.get(storage_account_key(grant, graph_id))


def storage_credentials_for(
    session_data: SessionData, grant: StorageGrant | None
) -> StorageCredentials | None:
    """`pick_storage_credentials` over the accounts of `session_data`, for a node of its graph."""
    return pick_storage_credentials(
        grant,
        session_data.graph.graph_id,
        session_data.storage_credentials,
        session_data.storage_credentials_by_grant,
    )
