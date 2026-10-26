"""Ownership rows whose resource still exists.

Deleting a resource leaves its `PluginOwnedResource` row in place: a delete listener on an
ownable model would turn off Django's column deferral for every cascaded row of it, so an
organization delete would load every flow in full. A row whose resource is gone is a
tombstone. Its pk is never reused, so it can never match a resource that is run or purged,
and a periodic sweep removes it. Anything that counts or lists what a plugin owns goes
through this module.

Each query names only the models its rows can be of. An `OR` of an `EXISTS` for every
ownable model makes Postgres plan the statement with JIT once it covers a few hundred rows,
which costs hundreds of milliseconds; one model's `EXISTS` per query does not.
"""

import operator
from collections import defaultdict
from collections.abc import Iterable
from functools import reduce

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Exists, Model, OuterRef, Q, QuerySet

from plugins.models import PluginOwnedResource
from plugins.ownership.ownership_recorder import ownable_models


def existing_owned_resources(
    owned: QuerySet[PluginOwnedResource], models: Iterable[type[Model]] | None = None
) -> QuerySet[PluginOwnedResource]:
    """Return the rows of `owned` whose resource still exists, binned ones included.

    One SQL statement: an `EXISTS` per model of `models` (every ownable model when None),
    each behind its content type, whose ids Django caches per process. Rows of a model not in
    `models` are left out. The base manager sees soft-deleted rows, so a resource in the
    recycle bin still counts. `owned` may be correlated (`OuterRef`), to count inside a
    subquery.
    """
    content_types = ContentType.objects.get_for_models(
        *(ownable_models() if models is None else models)
    )
    resource_exists = reduce(
        operator.or_,
        (
            Q(content_type_id=content_type.pk)
            & Exists(model._base_manager.filter(pk=OuterRef("object_id")))
            for model, content_type in content_types.items()
        ),
    )
    return owned.filter(resource_exists)


def existing_owned_counts(
    owned: QuerySet[PluginOwnedResource],
) -> dict[tuple[int | None, int], int]:
    """Count the rows of `owned` whose resource still exists, by `(grant id, content type id)`.

    One query for the content types present, then one per content type, each with only its
    own model's `EXISTS`. A content type whose model is gone from the code is skipped.
    """
    ownable = set(ownable_models())
    content_type_ids = owned.order_by().values_list("content_type_id", flat=True).distinct()
    counts: dict[tuple[int | None, int], int] = {}
    for content_type_id in list(content_type_ids):
        model = ContentType.objects.get_for_id(content_type_id).model_class()
        if model not in ownable:
            continue
        rows = (
            existing_owned_resources(owned.filter(content_type_id=content_type_id), [model])
            .order_by()
            .values("grant_id")
            .annotate(count=Count("pk"))
            .values_list("grant_id", "count")
        )
        for grant_id, count in rows:
            counts[(grant_id, content_type_id)] = count
    return counts


def owned_resource_counts_by_grant(grant_ids: Iterable[int]) -> dict[int, int]:
    """How many existing resources each grant's plugin owns; grants owning none are left out."""
    totals: dict[int, int] = defaultdict(int)
    owned = PluginOwnedResource.objects.filter(grant_id__in=list(grant_ids))
    for (grant_id, _), count in existing_owned_counts(owned).items():
        totals[grant_id] += count
    return dict(totals)


def owned_existing_ids(grant_id: int, model: type[Model], object_ids: Iterable[int]) -> set[int]:
    """The ids among `object_ids` of `model` rows the plugin owns under grant `grant_id` that
    still exist. One query with only `model`'s `EXISTS`; none for no ids."""
    object_ids = list(object_ids)
    if not object_ids:
        return set()
    owned = PluginOwnedResource.objects.filter(
        grant_id=grant_id,
        content_type=ContentType.objects.get_for_model(model),
        object_id__in=object_ids,
    )
    return set(existing_owned_resources(owned, [model]).values_list("object_id", flat=True))
