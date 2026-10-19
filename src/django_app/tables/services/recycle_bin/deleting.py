"""Moving a recycle-bin root to the bin, and recording who did it.

A binned row can't be edited, so its last edit is its deletion: the deleter is
recorded as the root's last edit (ResourceLastEdit), at the root's
`soft_deleted_at`. The bin's "Deleted by" reads that row, and after a restore
"Last edited by" shows who deleted it.
"""

import datetime
import uuid
from collections.abc import Sequence

from django.db import transaction
from rbac.authorship import RecordedLastEdit, record_last_edits, restore_last_edits
from rbac.models import LastEditTrackedModel


def move_to_recycle_bin(root: LastEditTrackedModel, user: object | None) -> uuid.UUID | None:
    """Move `root` (with its subtree) to the recycle bin and record `user` as who deleted it.

    `root` is a recycle-bin resource: soft-deletable and last-edit tracked (a test
    checks every one in the registry is both).

    Every path that bins a recycle-bin root goes through here; pass None when no
    person asked for it (a management command).

    Returns:
        The batch, or None when `root` was already binned: the first delete's record stays.
    """
    with transaction.atomic():
        batch = root.delete()
        if batch is not None:
            record_deleter([root], user, deleted_at=root.soft_deleted_at)
    return batch


def record_deleter(
    roots: Sequence[LastEditTrackedModel], user: object | None, *, deleted_at: datetime.datetime
) -> None:
    """Record `user` as the last editor of each bin entry it just deleted, at `deleted_at`.

    Only the entries, not the rows binned with them. No person (None) and a user that
    resolves to no author (a system API key) both record a NULL editor, so "Deleted by"
    never shows whoever edited the row before. Rows that opt out via
    `records_last_edit()` (built-in tools) get no record.
    """
    if user is None:
        restore_last_edits(RecordedLastEdit(root, None, deleted_at) for root in roots)
    else:
        record_last_edits(roots, user, edited_at=deleted_at)
