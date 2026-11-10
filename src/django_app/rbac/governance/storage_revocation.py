from collections.abc import Iterable

from django.db import transaction

from rbac.models import ApiKey


def revoke_storage_access_on_commit(
    *,
    org_id: int | None,
    user_ids: Iterable[int] = (),
    api_key_ids: Iterable[int] = (),
) -> None:
    """Revoke the temporary storage accounts of these users and API keys once the change commits.

    Called by the governance code that changes an identity's access (role or
    membership change, key revoked or deleted, user deactivated): an account
    carries the FILES permissions its identity held when it was minted, so a run
    in flight must lose it. A user's USER API keys act with the user's permissions,
    so their accounts are covered too. `org_id=None` covers every organization.

    The accounts are looked up now and again at commit. Now, because the change may
    delete the key or user the account is linked to, which clears the link; at
    commit, to catch an account minted while the change was still open.
    """
    # Imported here: storage_credentials imports rbac at module level.
    from storage_credentials.services.session_credential_service import (
        session_credential_service,
    )

    user_ids = list(user_ids)
    owned_keys = ApiKey.objects.filter(created_by_id__in=user_ids)
    if org_id is not None:
        owned_keys = owned_keys.filter(org_id=org_id)
    all_api_key_ids = set(api_key_ids) | set(owned_keys.values_list("pk", flat=True))

    access_keys = session_credential_service.access_keys_for_identity(
        org_id=org_id, user_ids=user_ids, api_key_ids=all_api_key_ids
    )

    def revoke() -> None:
        session_credential_service.revoke_access_keys(access_keys)
        session_credential_service.revoke_for_identity(
            org_id=org_id, user_ids=user_ids, api_key_ids=all_api_key_ids
        )

    transaction.on_commit(revoke, robust=True)
