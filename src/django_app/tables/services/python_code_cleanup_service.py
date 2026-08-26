from functools import cache
from typing import Iterable

from django.db import models, transaction
from django.db.models import Exists, OuterRef, Q
from loguru import logger

from tables.models.python_models import PythonCode


class PythonCodeCleanupService:
    """Deletes PythonCode rows once no CASCADE owner references them.

    The owner FKs run owner -> PythonCode with on_delete=CASCADE, so the DB
    only cascades in the PythonCode-deleted direction; nothing reclaims a row
    when its last owner goes away. This service is that missing direction.
    """

    @classmethod
    @cache
    def owner_relations(cls) -> tuple:
        return tuple(
            relation
            for relation in PythonCode._meta.related_objects
            if relation.on_delete is models.CASCADE
        )

    @classmethod
    def owner_fields_by_model(cls) -> dict[type, list[str]]:
        owners: dict[type, list[str]] = {}
        for relation in cls.owner_relations():
            owners.setdefault(relation.related_model, []).append(relation.field.attname)
        return owners

    @classmethod
    def _owned_by_any_owner(cls) -> Q:
        condition = Q()
        for relation in cls.owner_relations():
            condition |= Q(
                Exists(
                    relation.related_model.objects.filter(
                        **{relation.field.attname: OuterRef("id")}
                    )
                )
            )
        return condition

    @classmethod
    def delete_orphaned(cls, python_code_ids: Iterable[int | None]) -> int:
        """Delete the given PythonCode rows that have no owner left."""
        ids = {code_id for code_id in python_code_ids if code_id is not None}
        if not ids:
            return 0

        owners = cls._owned_by_any_owner()
        if not owners:
            return 0

        with transaction.atomic():
            locked_ids = set(
                PythonCode.objects.select_for_update()
                .filter(id__in=ids)
                .values_list("id", flat=True)
            )
            deleted, _ = (
                PythonCode.objects.filter(id__in=locked_ids).exclude(owners).delete()
            )

        if deleted:
            logger.debug("Deleted {deleted} orphaned PythonCode rows", deleted=deleted)
        return deleted
