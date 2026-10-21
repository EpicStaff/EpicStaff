"""Bin entries with what a restore of each would bring back: a flow's nodes, an
agent's own surfaces, a surface's tools and sources, a collection's documents.

The machinery only: what each resource shows is its BinPresentation, in presentation.py.
"""

import operator
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from functools import reduce

from django.db.models import (
    Count,
    Expression,
    F,
    IntegerField,
    Model,
    OuterRef,
    QuerySet,
    Subquery,
    Value,
    Window,
)
from django.db.models.functions import Coalesce, RowNumber
from rbac.authorship.policy import AUTHOR_FIELD, has_author_field
from tables.services.recycle_bin.authorship import (
    BinEntryAuthorship,
    DeletedWith,
    authorship_details,
)
from tables.services.recycle_bin.bin_service import (
    DEFAULT_ENTRY_ORDERING,
    RecycleBinEntry,
    RecycleBinService,
)
from tables.services.recycle_bin.presentation import (
    BinContent,
    BinDetail,
    BinPresentation,
    ContentSource,
    DetailContext,
)
from tables.services.recycle_bin.registry import BinResource

# A row lists at most this many contents; `contents_total` has the full count.
CONTENTS_LIMIT = 100
# "Show all" sends at most this many; a bigger folder or flow says how many more there are.
SHOW_ALL_LIMIT = 5000
# The list's `contents` filter: rows whose restore brings back something, or nothing.
CONTENTS_FILTERS: dict[str, dict[str, int]] = {
    "some": {"contents_count__gt": 0},
    "none": {"contents_count": 0},
}


@dataclass(frozen=True)
class RecycleBinEntryWithContents(RecycleBinEntry):
    details: list[BinDetail] = field(default_factory=list)
    contents: list[BinContent] = field(default_factory=list)
    contents_total: int = 0


class BinContentsService:
    @classmethod
    def entry_rows(
        cls,
        resource: BinResource,
        presentation: BinPresentation,
        org_id: int,
        *,
        search: str = "",
        ordering: str = DEFAULT_ENTRY_ORDERING,
        contents: str = "",
    ) -> QuerySet:
        """The org's bin rows for `resource`, filtered and sorted; pass a page of it to to_entries.

        `contents` is "some" or "none" to keep only the rows whose restore brings back
        something, or nothing (the count to_entries sends as `contents_total`); anything
        else keeps every row. `search` and `ordering` are RecycleBinService.entry_rows'.
        """
        binned = RecycleBinService.binned(resource, org_id)
        if contents in CONTENTS_FILTERS:
            binned = binned.annotate(
                contents_count=cls._contents_count(presentation.content_sources)
            ).filter(**CONTENTS_FILTERS[contents])
        return RecycleBinService.entry_rows(resource, binned, search=search, ordering=ordering)

    @classmethod
    def to_entries(
        cls,
        resource: BinResource,
        presentation: BinPresentation,
        org_id: int,
        rows,
    ) -> list[RecycleBinEntryWithContents]:
        """Entries for a page of entry_rows, each with what its restore brings back."""
        entries = RecycleBinService.to_entries(rows)
        batch_by_parent = {entry.id: entry.batch for entry in entries}
        contents, totals = cls._contents(
            presentation.content_sources,
            batch_by_parent,
            names=presentation.named_contents,
        )
        details = cls._details(
            resource, presentation, list(batch_by_parent), DetailContext(org_id=org_id)
        )
        return [
            RecycleBinEntryWithContents(
                **vars(entry),
                details=details.get(entry.id, []),
                contents=contents.get(entry.id, []),
                contents_total=totals.get(entry.id, 0),
            )
            for entry in entries
        ]

    @classmethod
    def contents_of(
        cls, presentation: BinPresentation, root: Model
    ) -> tuple[list[BinContent], int]:
        """One binned root's contents, up to SHOW_ALL_LIMIT: the bin's "Show all" for that row.

        A resource whose contents are only counted (a table's keys) lists none.
        """
        contents, totals = cls._contents(
            presentation.content_sources,
            {root.pk: root.soft_delete_batch},
            names=presentation.named_contents,
            limit=SHOW_ALL_LIMIT,
        )
        return contents.get(root.pk, []), totals.get(root.pk, 0)

    @staticmethod
    def _contents_count(sources: tuple[ContentSource, ...]) -> Expression:
        """Per bin row, in SQL, how many rows its restore brings back: `_contents`' totals.

        One correlated count per source, of the rows binned in the entry's own batch.
        0 for a resource with nothing inside.
        """
        counts = [
            Coalesce(
                Subquery(
                    source.model.deleted_objects.filter(
                        **{source.parent_field: OuterRef("pk")},
                        soft_delete_batch=OuterRef("soft_delete_batch"),
                    )
                    .order_by()
                    .values(source.parent_field)
                    .annotate(count=Count("pk"))
                    .values("count"),
                    output_field=IntegerField(),
                ),
                0,
            )
            for source in sources
        ]
        return reduce(operator.add, counts, Value(0, output_field=IntegerField()))

    @staticmethod
    def _contents(
        sources: tuple[ContentSource, ...],
        batch_by_parent: dict[int, uuid.UUID],
        *,
        names: bool = True,
        limit: int | None = CONTENTS_LIMIT,
    ) -> tuple[dict[int, list[BinContent]], dict[int, int]]:
        """Two queries per source (one without `names`), whatever the number of entries.

        `limit` caps the names per entry (None for all of them).

        A row counts only if it's binned in its entry's own batch: that's what a
        restore of the entry brings back. One deleted on its own before has
        another batch and stays in the bin.
        """
        contents: dict[int, list[BinContent]] = defaultdict(list)
        totals: dict[int, int] = defaultdict(int)
        if not batch_by_parent:
            return contents, totals
        batches = set(batch_by_parent.values())
        for source in sources:
            rows = source.model.deleted_objects.filter(
                **{f"{source.parent_field}__in": batch_by_parent.keys()},
                soft_delete_batch__in=batches,
            )
            for parent_id, batch, count in rows.values_list(
                source.parent_field, "soft_delete_batch"
            ).annotate(count=Count("pk")):
                if batch == batch_by_parent[parent_id]:
                    totals[parent_id] += count
            if not names:
                continue
            named = rows
            if limit is not None:
                named = rows.annotate(
                    # Per (entry, batch): rows the entry lost in other deletes
                    # must not use up the cap of the batch it would restore.
                    position=Window(
                        RowNumber(),
                        partition_by=[F(source.parent_field), F("soft_delete_batch")],
                        order_by=F("pk").asc(),
                    )
                ).filter(position__lte=limit)
            for parent_id, batch, name in named.order_by("pk").values_list(
                source.parent_field, "soft_delete_batch", source.name_field
            ):
                if batch == batch_by_parent[parent_id]:
                    contents[parent_id].append(BinContent(name=name or "", kind=source.kind))
        return contents, totals

    @staticmethod
    def _details(
        resource: BinResource,
        presentation: BinPresentation,
        ids: list[int],
        context: DetailContext,
    ) -> dict[int, list[BinDetail]]:
        """Basic info per entry: who created and who deleted it first, then the tab's fields.

        Three queries for the whole list (the fields, the last edits, the users), plus
        a resource's extra lines. Every field of the tab is sent, with a null value when
        it's empty.

        Only plain descriptive fields: never secrets, URLs with credentials or keys.
        """
        if not ids:
            return {}
        fields = presentation.detail_fields
        paths = {path for detail_field in fields for path in detail_field.paths}
        paths.add("soft_deleted_at")
        author_path = f"{AUTHOR_FIELD}_id" if has_author_field(resource.model) else None
        if author_path is not None:
            paths.add(author_path)
        owner = resource.owner_field
        if owner is not None:
            paths |= {
                f"{owner}__active",
                f"{owner}_id",
                f"{owner}__soft_delete_batch",
                "soft_delete_batch",
            }
        extra = (
            presentation.extra_details(ids, context)
            if presentation.extra_details is not None
            else {}
        )
        rows = list(resource.model.all_objects.filter(pk__in=ids).values("pk", *paths))
        authorship = authorship_details(
            resource.model,
            {
                row["pk"]: BinEntryAuthorship(
                    row[author_path] if author_path else None, row["soft_deleted_at"]
                )
                for row in rows
            },
            deleted_with=_deleted_with_owner(resource, rows),
        )
        details: dict[int, list[BinDetail]] = {}
        for row in rows:
            lines = list(authorship[row["pk"]])
            for detail_field in fields:
                lines.append(
                    BinDetail(
                        label=detail_field.label_of(row),
                        value=detail_field.render(row),
                        format=detail_field.format,
                    )
                )
            lines += extra.get(row["pk"], [])
            # False only when there is an owner and it's binned (no owner gives None):
            # RestoreService then brings the row back without its owner.
            if resource.owner_field is not None and row[f"{resource.owner_field}__active"] is False:
                lines.append(
                    BinDetail(
                        label="Comes back as",
                        value="Shared. Its owner is in the recycle bin. Restore the owner to get it back as its own.",
                        format="notice",
                    )
                )
            details[row["pk"]] = lines
        return details


def _deleted_with_owner(resource: BinResource, rows: list[dict]) -> dict[int, DeletedWith]:
    """The entries binned in their owner's batch (a surface deleted with its agent), with that owner."""
    owner = resource.owner_field
    if owner is None:
        return {}
    owner_model = resource.model._meta.get_field(owner).related_model
    return {
        row["pk"]: (owner_model, row[f"{owner}_id"])
        for row in rows
        if row[f"{owner}_id"] is not None
        and row["soft_delete_batch"] is not None
        and row["soft_delete_batch"] == row[f"{owner}__soft_delete_batch"]
    }
