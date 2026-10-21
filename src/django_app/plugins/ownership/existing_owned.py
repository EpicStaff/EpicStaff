"""Ownership rows whose resource still exists.

Deleting a resource leaves its `PluginOwnedResource` row in place: a delete listener on an
ownable model would turn off Django's column deferral for every cascaded row of it, so an
organization delete would load every flow in full. A row whose resource is gone is a
tombstone. Its pk is never reused, so it can never match a resource that is run or purged,
and a periodic sweep removes it. Anything that counts or lists what a plugin owns goes
through `existing_owned_resources`.
"""

import operator
from functools import reduce

from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, Model, OuterRef, Q, QuerySet

from plugins.models import PluginOwnedResource
from plugins.ownership.ownership_recorder import ownable_models


def existing_owned_resources(
    owned: QuerySet[PluginOwnedResource],
) -> QuerySet[PluginOwnedResource]:
    """Return the rows of `owned` whose resource still exists, binned ones included.

    One SQL statement whatever the number of ownable models: an `EXISTS` per model, each
    behind its content type (whose ids Django caches per process). The base manager sees
    soft-deleted rows, so a resource in the recycle bin still counts. `owned` may be
    correlated (`OuterRef`), to count inside a subquery.
    """
    content_types = ContentType.objects.get_for_models(*ownable_models())
    resource_exists = reduce(
        operator.or_,
        (
            Q(content_type_id=content_type.pk)
            & Exists(model._base_manager.filter(pk=OuterRef("object_id")))
            for model, content_type in content_types.items()
        ),
    )
    return owned.filter(resource_exists)


def grant_owns_every(grant_id: int, model: type[Model], object_ids: frozenset[int]) -> bool:
    """Return whether the plugin owns, under grant `grant_id`, an existing `model` row per id.

    One query. True for no ids at all.
    """
    if not object_ids:
        return True
    owned = PluginOwnedResource.objects.filter(
        grant_id=grant_id,
        content_type=ContentType.objects.get_for_model(model),
        object_id__in=object_ids,
    )
    # (content type, object id) is unique, so one row per owned id.
    return existing_owned_resources(owned).count() == len(object_ids)
