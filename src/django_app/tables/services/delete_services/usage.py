"""Result and usage-report types shared by every entity bulk-delete service."""

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
    """One referencing entity in a usage sample."""

    resource_type: str
    id: int
    name: str | None


@dataclass(frozen=True)
class UsageBucket:
    """References to one entity from one resource type, split by visibility.

    `total_count` drives `has_hidden` but is never serialised: it would reveal how
    much exists behind a permission boundary.
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
    """Every bucket for one entity; blocked when any bucket has hidden references."""

    buckets: list[UsageBucket] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(bucket.has_hidden for bucket in self.buckets)


class BucketCollector:
    """Accumulates one resource-type bucket, counting each referencing parent once.

    Several FK paths can reach the same parent (an agent naming one config as both
    its primary and tool-call model), so references are keyed by the parent id.
    Every id in a bucket points at the same parent table, so the id alone is unique.
    """

    def __init__(self, resource_type: str, *, visible: bool) -> None:
        self.resource_type = resource_type
        self.visible = visible
        self._refs: defaultdict[int, dict[int, UsageRef]] = defaultdict(dict)

    @classmethod
    def for_resource(
        cls, resource_type: ResourceType, permissions: EffectivePermissions
    ) -> "BucketCollector":
        """A collector whose references are visible when the caller holds READ on the type."""
        return cls(
            resource_type.value,
            visible=permissions.can(resource_type.value, Permission.READ),
        )

    def add(self, entity_id: int, ref_id: int, ref_name: str | None) -> None:
        """Record one reference, ignoring it if this parent is already known."""
        self._refs[entity_id].setdefault(
            ref_id,
            UsageRef(resource_type=self.resource_type, id=ref_id, name=ref_name),
        )

    def add_rows(self, rows: Iterable[tuple[int, int, str | None]]) -> None:
        """Record `(entity_id, ref_id, ref_name)` triples."""
        for entity_id, ref_id, ref_name in rows:
            self.add(entity_id, ref_id, ref_name)

    def bucket_for(self, entity_id: int) -> UsageBucket:
        # Sorted because the source queries have no ORDER BY: the capped sample
        # must not shift between a preview and a refresh.
        refs = sorted(self._refs.get(entity_id, {}).values(), key=lambda ref: ref.id)
        return UsageBucket(
            resource_type=self.resource_type,
            total_count=len(refs),
            visible_refs=refs if self.visible else [],
        )


def build_reports(
    ids: Iterable[int], collectors: Iterable[BucketCollector]
) -> dict[int, UsageReport]:
    """One report per id, including ids with no references, so the shape never varies."""
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
    """The outcome of one bulk-delete or preview call.

    `deletable_ids` is "what would go"; `deleted_ids` is "what went" and stays
    empty on a preview, so a preview cannot be misread as a deletion.
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
        """True when some requested id was not found or was left alone."""
        return bool(self.not_found_ids or self.skipped)
