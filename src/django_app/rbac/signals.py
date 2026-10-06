from collections.abc import Iterable

import django.dispatch
from django.db import transaction

# Sent after a user's own profile changes (display name, avatar). Receivers get
# `user`. Kept in rbac so the profile surface needs no knowledge of who reacts.
profile_updated = django.dispatch.Signal()

# Sent after a change that may have reduced one user's access in one
# organization (role changed, membership removed, role permissions edited or
# role deleted, organization deactivated or deleted). Receivers get `user_id`
# and `org_id`. Send it only through `send_org_access_changed_on_commit`,
# never mid-write.
org_access_changed = django.dispatch.Signal()

# Sent after a change that may have reduced a user's access in every
# organization at once (superadmin revoked, account deactivated or deleted).
# Receivers get `user_id`. Send it only through
# `send_user_access_changed_on_commit`, never mid-write.
user_access_changed = django.dispatch.Signal()


def send_org_access_changed_on_commit(sender, org_id: int, user_ids: Iterable[int]) -> None:
    """Send `org_access_changed` for each user once the transaction commits.

    `user_ids` is read here, at call time. Callers must still read the ids
    before any delete or bulk reassign that removes the rows they come from.
    Each send is robust: a failing receiver is logged and never undoes the
    commit or skips the other users.
    """
    for user_id in list(user_ids):
        transaction.on_commit(
            lambda user_id=user_id, org_id=org_id: org_access_changed.send(
                sender=sender, user_id=user_id, org_id=org_id
            ),
            robust=True,
        )


def send_user_access_changed_on_commit(sender, user_id: int) -> None:
    """Send `user_access_changed` for one user once the transaction commits (robust)."""
    transaction.on_commit(
        lambda user_id=user_id: user_access_changed.send(sender=sender, user_id=user_id),
        robust=True,
    )
