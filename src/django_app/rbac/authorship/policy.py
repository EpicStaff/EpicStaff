from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from rbac.models.organization_user import OrganizationUser

if TYPE_CHECKING:
    from tables.models.user import User

AUTHOR_FIELD = "created_by"


def resolve_author(user: object) -> "User | None":
    """Return `user` if it can be recorded as an author, otherwise None.

    Only persisted, authenticated user rows qualify; `AnonymousUser` and the
    system API-key principal resolve to no author.
    """
    if isinstance(user, get_user_model()) and user.pk is not None and user.is_authenticated:
        return user
    return None


def org_member_ids(*, org_id: int, user_ids: Iterable[int | None]) -> set[int]:
    """Return the subset of `user_ids` that are members of organization `org_id`.

    One query; None ids are ignored.
    """
    known_user_ids = {user_id for user_id in user_ids if user_id is not None}
    if not known_user_ids:
        return set()
    return set(
        OrganizationUser.objects.filter(org_id=org_id, user_id__in=known_user_ids).values_list(
            "user_id", flat=True
        )
    )


def has_author_field(model: type[models.Model]) -> bool:
    """Return whether `model` records an author in a `created_by` field."""
    try:
        model._meta.get_field(AUTHOR_FIELD)
    except FieldDoesNotExist:
        return False
    return True
