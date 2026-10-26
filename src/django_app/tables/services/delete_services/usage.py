"""Shared vocabulary for every entity bulk-delete service.

Holds the wire contract — skip reasons, usage report shape, bulk result — in
one place, so each entity service carries only its own referencing-source
knowledge, and the response shape and the 200/207 rule cannot drift apart
between entities.

Nothing here knows about HTTP. `BulkDeleteResult.is_partial` states the domain
fact -- "not everything the caller asked for happened" -- and the view layer
maps that to 207 on a real delete; see BulkDeleteActionMixin.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import models
from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType

SAMPLE_LIMIT = 5


class SkipReason(models.TextChoices):
    """Why an existing row was left alone instead of deleted."""

    IN_USE_RESTRICTED = (
        "in_use_restricted",
        "Referenced by resources the caller cannot see",
    )
    PROTECTED = "protected", "Blocked by a database-level delete guard"


@dataclass(frozen=True)
class UsageRef:
    """One referencing entity in a usage sample.

    `resource_type` names the permission bucket it is counted under, which
    decides whether the caller may see it.
    """

    resource_type: str
    id: int
    name: str | None


@dataclass(frozen=True)
class UsageBucket:
    """References to one entity from one resource type, split by visibility.

    `total_count` drives `has_hidden` but never reaches the wire: disclosing it
    would tell the caller how much exists behind a permission boundary. Only
    `visible_count` and `visible_sample` are serialised.
    """

    resource_type: str
    total_count: int
    visible_refs: list[UsageRef]

    @property
    def visible_count(self) -> int:
        return len(self.visible_refs)

    @property
    def has_hidden(self) -> bool:
        return self.total_count > self.visible_count

    @property
    def truncated(self) -> bool:
        return self.visible_count > SAMPLE_LIMIT

    @property
    def visible_sample(self) -> list[UsageRef]:
        return self.visible_refs[:SAMPLE_LIMIT]


@dataclass(frozen=True)
class UsageReport:
    """Every bucket for one entity, plus the verdict derived from them.

    An entity with no referencing sources at all (GraphVersion) reports an
    empty bucket list rather than being left out of the response -- the whole
    family shares one shape, so a client needs no per-entity branch.
    """

    buckets: list[UsageBucket] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(bucket.has_hidden for bucket in self.buckets)


class BucketCollector:
    """Accumulates deduplicated references for one resource-type bucket.

    Several FK paths routinely reach the same parent -- an AgentDefinition
    naming one LLMConfig as both its `llm_config` and its `fcm_llm_config` is
    *one* agent, not two; a Flow reaching a config through both a
    decision-table node and an assistant is one flow. Collecting through a
    keyed map makes double-counting structurally impossible, instead of
    leaving each collector to remember a dedup pass.

    `.distinct()` on the underlying queryset does not help: it is per-query, so
    it cannot deduplicate rows that several queries append into one bucket.

    References are keyed on `ref_id`: every id in a bucket points at the same
    parent table, so the id alone is unique.
    """

    def __init__(self, resource_type: str, *, visible: bool) -> None:
        self.resource_type = resource_type
        self.visible = visible
        self._refs: defaultdict[int, dict[int, UsageRef]] = defaultdict(dict)

    @classmethod
    def for_resource(
        cls, resource_type: ResourceType, effective: EffectivePermissions
    ) -> "BucketCollector":
        """A collector visible exactly when the caller holds READ on the type.

        Visibility is all-or-nothing per organization today: READ on the
        resource type reveals every reference, lacking it reveals none. There is
        no instance-level ACL yet, and this is the single place -- for every
        entity -- that a per-row filter would go when one lands.
        """
        return cls(
            resource_type.value,
            visible=effective.can(resource_type.value, Permission.READ),
        )

    def add(self, entity_id: int, ref_id: int, ref_name: str | None) -> None:
        """Record one reference, ignoring it if this parent is already known."""
        self._refs[entity_id].setdefault(
            ref_id,
            UsageRef(
                resource_type=self.resource_type,
                id=ref_id,
                name=ref_name,
            ),
        )

    def add_rows(self, rows: Iterable[tuple[int, int, str | None]]) -> None:
        """Record `(entity_id, ref_id, ref_name)` triples."""
        for entity_id, ref_id, ref_name in rows:
            self.add(entity_id, ref_id, ref_name)

    def bucket_for(self, entity_id: int) -> UsageBucket:
        # Sorted because the source queries have no ORDER BY: without it the
        # capped sample could differ between a preview and a refresh.
        refs = sorted(self._refs.get(entity_id, {}).values(), key=lambda ref: ref.id)
        return UsageBucket(
            resource_type=self.resource_type,
            total_count=len(refs),
            visible_refs=refs if self.visible else [],
        )


def build_reports(
    ids: Iterable[int], collectors: Iterable[BucketCollector]
) -> dict[int, UsageReport]:
    """One report per id, with every collector contributing a bucket.

    Every id gets an entry, including ids whose buckets are all empty, so the
    response shape does not vary between rows or between entities.
    """
    collectors = list(collectors)
    return {
        entity_id: UsageReport(
            buckets=[collector.bucket_for(entity_id) for collector in collectors]
        )
        for entity_id in ids
    }


@dataclass(frozen=True)
class SkipEntry:
    """One id that exists and was deliberately not deleted."""

    id: int
    reason: SkipReason


@dataclass(frozen=True)
class BulkDeleteResult:
    """The outcome of one bulk-delete call, for every entity.

    `deletable_ids` is populated in both modes -- it answers "what would go".
    `deleted_ids` answers "what actually went", and is empty on a dry run, so a
    preview can never be misread as a deletion.
    """

    dry_run: bool
    deletable_ids: list[int]
    deleted_ids: list[int]
    not_found_ids: list[int]
    skipped: list[SkipEntry]
    usage: dict[int, UsageReport]

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_ids)

    @property
    def is_partial(self) -> bool:
        """True when some requested id was not found or was left alone.

        The single definition of the rule for every entity. The view layer
        turns this into 207 Multi-Status on a real delete.
        """
        return bool(self.not_found_ids or self.skipped)
