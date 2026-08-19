from functools import reduce
from operator import or_

from django.db import models
from django.db.models import Exists, OuterRef, Q

from tables.models.python_models import PythonCode


def _owner_relations():
    return [
        relation
        for relation in PythonCode._meta.related_objects
        if relation.on_delete is models.CASCADE
    ]


OWNER_RELATIONS = tuple(_owner_relations())  # computed once, at import time


def _still_owned(relations) -> Q:
    """Q matching rows referenced by at least one of the given relations."""
    if not relations:
        return Q(pk__in=[])
    return reduce(
        or_,
        (
            Q(
                Exists(
                    relation.related_model.objects.filter(
                        **{relation.field.attname: OuterRef("id")}
                    )
                )
            )
            for relation in relations
        ),
    )


def delete_python_code(python_code_ids: set[int], *, exclude_model=None) -> None:
    """Delete PythonCode rows with zero remaining CASCADE owners, in one query.

    exclude_model skips checking the model whose instance just triggered this
    call via post_delete — its row is already gone, so it's excluded from the
    ownership check without adding a subquery for it.
    """
    ids = {code_id for code_id in python_code_ids if code_id is not None}
    if not ids:
        return

    relations = [r for r in OWNER_RELATIONS if r.related_model is not exclude_model]
    candidates = PythonCode.objects.filter(id__in=ids)
    candidates.exclude(_still_owned(relations)).delete()
