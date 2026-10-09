from collections.abc import Callable
from typing import Protocol

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db import models, transaction
from django.db.models import Q

from rbac.authorship.checks import MISSING_ORG_LOOKUP_CHECK_ID
from rbac.authorship.registry import author_tracked_models, last_edit_tracked_models
from rbac.models import OrganizationUser, ResourceLastEdit


class AuthorshipReleaseService:
    """Clear the authorship and last-editor records a user holds on organization resources."""

    def release(self, user_id: int, org_id: int) -> int:
        """Clear `user_id` as author and as last editor of every row in `org_id`.

        Last edits keep their time. Soft-deleted rows are included. Returns the number of
        author and last-edit rows released.
        """
        return self._release_matching(user_id, lambda lookup: Q(**{lookup: org_id}))

    def release_outside_memberships(self, user_id: int) -> int:
        """Clear the user as author and last editor in every org they are not a member of.

        Rows without an organization are kept, soft-deleted rows are included. Returns
        the number of author and last-edit rows released.
        """
        member_org_ids = OrganizationUser.objects.filter(user_id=user_id).values("org_id")
        return self._release_matching(
            user_id,
            lambda lookup: (
                Q(**{f"{lookup}__isnull": False}) & ~Q(**{f"{lookup}__in": member_org_ids})
            ),
        )

    def _release_matching(self, user_id: int, org_condition: Callable[[str], Q]) -> int:
        released = 0
        for model, org_lookup in self._tracked_models():
            released += (
                model._base_manager.filter(org_condition(org_lookup))
                .filter(created_by_id=user_id)
                .update(created_by=None)
            )
        return released + self._release_last_edits(user_id, org_condition)

    @staticmethod
    def _release_last_edits(user_id: int, org_condition: Callable[[str], Q]) -> int:
        released_resources = Q()
        for model, org_lookup in last_edit_tracked_models():
            released_resources |= Q(
                content_type=ContentType.objects.get_for_model(model),
                object_id__in=model._base_manager.filter(org_condition(org_lookup)).values("pk"),
            )
        return ResourceLastEdit.objects.filter(released_resources, edited_by_id=user_id).update(
            edited_by=None
        )

    @staticmethod
    def _tracked_models() -> list[tuple[type[models.Model], str]]:
        # The system check reports this at startup; failing before any update keeps
        # a misconfigured deployment from releasing only part of the rows.
        tracked = author_tracked_models()
        misconfigured = [model.__name__ for model, org_lookup in tracked if org_lookup is None]
        if misconfigured:
            raise ImproperlyConfigured(
                f"AuthorModel subclasses without author_org_lookup: {', '.join(misconfigured)} "
                f"(system check {MISSING_ORG_LOOKUP_CHECK_ID})."
            )
        return tracked


class SnapshotAuthorshipScrubber(Protocol):
    """An app that keeps snapshots recording users as authors or last editors.

    Restoring a snapshot replays the users it recorded, so a user who leaves an
    organization, loses the superadmin role while not a member of it, or is deleted, must
    not stay recorded in it. Each operation returns the number of snapshots it rewrote and
    locks them until the caller's transaction ends.
    """

    def scrub_in_organization(self, user_id: int, org_id: int) -> int:
        """Clear `user_id` from the snapshots recorded in `org_id`."""
        ...

    def scrub_in_every_organization(self, user_id: int) -> int:
        """Clear `user_id` from the snapshots of every organization."""
        ...

    def scrub_outside_memberships(self, user_id: int) -> int:
        """Clear `user_id` from the snapshots of every organization they are not a member of."""
        ...

    def scrub_every_user(self) -> int:
        """Clear every recorded user from every snapshot."""
        ...


_snapshot_scrubbers: list[SnapshotAuthorshipScrubber] = []


def register_snapshot_scrubber(scrubber: SnapshotAuthorshipScrubber) -> None:
    """Enrol a scrubber in every authorship scrub of `SnapshotAuthorshipScrubService`."""
    if any(type(registered) is type(scrubber) for registered in _snapshot_scrubbers):
        raise ValueError(f"{type(scrubber).__name__} is already registered")
    _snapshot_scrubbers.append(scrubber)


def snapshot_scrubbers() -> tuple[SnapshotAuthorshipScrubber, ...]:
    """Return the registered snapshot authorship scrubbers in registration order."""
    return tuple(_snapshot_scrubbers)


class SnapshotAuthorshipScrubService:
    """Clear users from the authorship every registered app recorded in its snapshots.

    Each operation runs every registered scrubber in one transaction and returns the
    total number of snapshots they rewrote.
    """

    @transaction.atomic
    def scrub_in_organization(self, user_id: int, org_id: int) -> int:
        """Clear `user_id` from the snapshots recorded in `org_id`."""
        return sum(
            scrubber.scrub_in_organization(user_id=user_id, org_id=org_id)
            for scrubber in snapshot_scrubbers()
        )

    @transaction.atomic
    def scrub_in_every_organization(self, user_id: int) -> int:
        """Clear `user_id` from the snapshots of every organization."""
        return sum(
            scrubber.scrub_in_every_organization(user_id=user_id)
            for scrubber in snapshot_scrubbers()
        )

    @transaction.atomic
    def scrub_outside_memberships(self, user_id: int) -> int:
        """Clear `user_id` from the snapshots of every organization they are not a member of."""
        return sum(
            scrubber.scrub_outside_memberships(user_id=user_id) for scrubber in snapshot_scrubbers()
        )

    @transaction.atomic
    def scrub_every_user(self) -> int:
        """Clear every recorded user from every snapshot."""
        return sum(scrubber.scrub_every_user() for scrubber in snapshot_scrubbers())
