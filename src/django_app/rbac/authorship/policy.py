from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import models

if TYPE_CHECKING:
    from tables.models.user import User


def resolve_author(user: object) -> "User | None":
    """Return `user` if it can be recorded as an author, otherwise None.

    Only persisted, authenticated user rows qualify; `AnonymousUser` and the
    system API-key principal resolve to no author.
    """
    if isinstance(user, get_user_model()) and user.pk is not None and user.is_authenticated:
        return user
    return None


def claim_authorship(instance: models.Model, user: object) -> bool:
    """Set `user` as the author of an instance with a `created_by` field when it has none.

    Returns True when the author was assigned, False when the instance already has an
    author or `user` does not resolve to one. The instance is not saved.
    """
    if instance.created_by_id is not None:
        return False
    author = resolve_author(user)
    if author is None:
        return False
    instance.created_by = author
    return True
