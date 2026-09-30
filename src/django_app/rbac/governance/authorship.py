from collections.abc import Callable

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Q

from rbac.authorship.checks import MISSING_ORG_LOOKUP_CHECK_ID
from rbac.authorship.registry import author_tracked_models
from rbac.models import OrganizationUser


class AuthorshipReleaseService:
    """Clear the authorship a user holds on organization resources."""

    def release(self, user_id: int, org_id: int) -> int:
        """Set `created_by` to NULL on every row in `org_id` authored by `user_id`.

        Soft-deleted rows are included. Returns the number of rows released.
        """
        return self._release_matching(user_id, lambda lookup: Q(**{lookup: org_id}))

    def release_outside_memberships(self, user_id: int) -> int:
        """Set `created_by` to NULL on the user's rows in every org they are not a member of.

        Rows without an organization are kept, soft-deleted rows are included. Returns
        the number of rows released.
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
        return released

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
