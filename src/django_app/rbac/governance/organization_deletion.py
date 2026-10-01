from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from rbac.governance.delete_collector import ModelCount
from rbac.governance.delete_resource_names import register_resource_names
from rbac.models import Organization

PostCommitCleanup = Callable[[], None]


@dataclass
class OrganizationDeletionCounts:
    """Rows and external artifacts one participant's sweep removes for an organization."""

    by_model: list[ModelCount] = field(default_factory=list)
    external_counts: dict[str, int] = field(default_factory=dict)


class OrganizationDeletionParticipant(Protocol):
    """An app that removes the organization-owned data of its own models that the Collector cascade misses."""

    def count_external_artifacts(self, organization: Organization) -> dict[str, int]:
        """Count the artifacts outside the database this delete would orphan, degrading to no count instead of raising."""
        ...

    def count(self, organization: Organization) -> OrganizationDeletionCounts:
        """Count what `sweep` would remove, without writing anything."""
        ...

    def sweep(self, organization: Organization) -> PostCommitCleanup | None:
        """Delete the rows the Collector cascade would miss or orphan, and return the cleanup to run once the delete commits."""
        ...

    def resource_names(self) -> dict[str, str]:
        """Return the delete report's friendly resource name for each of this app's model labels."""
        ...

    def excluded_resource_labels(self) -> frozenset[str]:
        """Return this app's model labels that the delete report deliberately leaves out."""
        ...


_participants: list[OrganizationDeletionParticipant] = []


def register_participant(participant: OrganizationDeletionParticipant) -> None:
    """Enrol a participant in every organization delete and add its model labels to the delete report."""
    if any(type(registered) is type(participant) for registered in _participants):
        raise ValueError(f"{type(participant).__name__} is already registered")
    register_resource_names(participant.resource_names(), participant.excluded_resource_labels())
    _participants.append(participant)


def participants() -> tuple[OrganizationDeletionParticipant, ...]:
    """Return the registered organization deletion participants in registration order."""
    return tuple(_participants)
