"""Who created and who deleted each bin entry: the first two detail lines on every tab."""

import datetime
from collections import defaultdict
from collections.abc import Mapping
from typing import NamedTuple

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, Q
from rbac.authorship import user_summaries_by_id
from rbac.models import ResourceLastEdit
from tables.services.recycle_bin.presentation import BinDetail

CREATED_BY_LABEL = "Created by"
DELETED_BY_LABEL = "Deleted by"


class BinEntryAuthorship(NamedTuple):
    """What a bin entry's authorship lines are read from."""

    author_id: int | None  # `created_by`; None for no author or a model without one
    deleted_at: datetime.datetime  # `soft_deleted_at`


# The resource a bin entry was binned with, as (model, id): an owner deleted
# together with the row it owns.
DeletedWith = tuple[type[Model], int]


def authorship_details(
    model: type[Model],
    entries: Mapping[int, BinEntryAuthorship],
    *,
    deleted_with: Mapping[int, DeletedWith] | None = None,
) -> dict[int, list[BinDetail]]:
    """The "Created by" and "Deleted by" lines of each entry, keyed by entry id.

    Two queries, whatever the number of entries. The deleter is the last edit
    recorded at the entry's deletion time (move_to_recycle_bin writes it there); a
    last edit from before the deletion is an editor, not the deleter, so an entry
    binned before deleters were recorded shows none. A line's value is the user's
    summary, or None when the user is unknown: no record, a system principal, a
    deleted user, or one who has left the organization (AuthorshipReleaseService
    clears both the author and the last editor).

    Args:
        entries: Each entry's author and deletion time, keyed by entry id.
        deleted_with: The owner an entry was binned with, whose deleter is the entry's
            too: deleting an agent bins its surfaces, but only the agent the user picked
            records the deletion.
    """
    deleter_ids = _deleter_ids(model, entries, deleted_with or {})
    summaries = user_summaries_by_id(
        [*(entry.author_id for entry in entries.values()), *deleter_ids.values()]
    )
    return {
        entry_id: [
            BinDetail(label=CREATED_BY_LABEL, value=summaries.get(entry.author_id), format="user"),
            BinDetail(
                label=DELETED_BY_LABEL,
                value=summaries.get(deleter_ids.get(entry_id)),
                format="user",
            ),
        ]
        for entry_id, entry in entries.items()
    }


def _deleter_ids(
    model: type[Model],
    entries: Mapping[int, BinEntryAuthorship],
    deleted_with: Mapping[int, DeletedWith],
) -> dict[int, int | None]:
    """Each entry's deleter id: the owner's for an entry binned with its owner, else its own."""
    if not entries:
        return {}
    entry_content_type_id = ContentType.objects.get_for_model(model).pk
    ids_by_content_type: dict[int, set[int]] = defaultdict(set)
    recorded_on: dict[int, tuple[int, int]] = {}
    for entry_id in entries:
        if entry_id in deleted_with:
            owner_model, owner_id = deleted_with[entry_id]
            key = (ContentType.objects.get_for_model(owner_model).pk, owner_id)
        else:
            key = (entry_content_type_id, entry_id)
        recorded_on[entry_id] = key
        ids_by_content_type[key[0]].add(key[1])
    wanted = Q()
    for content_type_id, object_ids in ids_by_content_type.items():
        wanted |= Q(content_type_id=content_type_id, object_id__in=object_ids)
    last_edits = {
        (content_type_id, object_id): (edited_by_id, edited_at)
        for content_type_id, object_id, edited_by_id, edited_at in ResourceLastEdit.objects.filter(
            wanted
        ).values_list("content_type_id", "object_id", "edited_by_id", "edited_at")
    }
    deleter_ids = {}
    for entry_id, entry in entries.items():
        edited_by_id, edited_at = last_edits.get(recorded_on[entry_id], (None, None))
        # Rows binned together share their deletion time, so an owner's deletion
        # record carries the entry's own soft_deleted_at.
        deleter_ids[entry_id] = edited_by_id if edited_at == entry.deleted_at else None
    return deleter_ids
