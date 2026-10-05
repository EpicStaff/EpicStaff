from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db import models

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


def claim_authorship_in_bulk(instances: Iterable[models.Model], author: "User") -> None:
    """Persist `author` as the author of every instance with a `created_by` field and none set.

    Instances already authored in memory cost no query; the NULL check runs in one UPDATE
    per model, so an author set since an instance was loaded is never replaced.
    """
    ids_by_model: dict[type[models.Model], set[Any]] = defaultdict(set)
    for instance in instances:
        if has_author_field(type(instance)) and instance.created_by_id is None:
            ids_by_model[instance._meta.concrete_model].add(instance.pk)
    for model, ids in ids_by_model.items():
        model._base_manager.filter(pk__in=ids, created_by__isnull=True).update(created_by=author)


def has_author_field(model: type[models.Model]) -> bool:
    """Return whether `model` records an author in a `created_by` field."""
    try:
        model._meta.get_field(AUTHOR_FIELD)
    except FieldDoesNotExist:
        return False
    return True
