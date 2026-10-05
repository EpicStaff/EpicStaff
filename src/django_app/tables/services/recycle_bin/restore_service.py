from dataclasses import dataclass
from functools import cache

from django.apps import apps
from django.db import models, transaction
from django.db.models.signals import post_save
from loguru import logger
from tables.exceptions import NotInRecycleBinError
from tables.models.base_models import SoftDeleteFields
from tables.services.copy_services.helpers import next_copy_name
from tables.services.recycle_bin.registry import BinResource, bin_resource_for

_RESTORED_FIELDS = ["active", "soft_deleted_at", "soft_delete_batch"]


@dataclass
class RestoreResult:
    """The restored root, and its old name when a restore had to rename it."""

    object: models.Model
    renamed_from: str | None


@cache
def _soft_delete_models() -> tuple[type[models.Model], ...]:
    return tuple(
        model
        for model in apps.get_models()
        if issubclass(model, SoftDeleteFields) and not model._meta.proxy
    )


class RestoreService:
    """Brings recycle-bin roots back with everything deleted in the same batch."""

    @classmethod
    def restore(cls, root: models.Model) -> RestoreResult:
        """Bring a recycle-bin root back, with every row deleted in the same batch.

        Rows deleted on their own earlier (another batch) stay in the bin. If the
        root's name is taken among the org's live rows, it gets the next free
        "#N" name, the same pattern a copy uses.

        Raises:
            NotInRecycleBinError: The root isn't binned, or was binned before
                batches existed (restoring it would match every such row).
        """
        resource = bin_resource_for(type(root))
        with transaction.atomic():
            stored = (
                resource.model.all_objects.select_for_update()
                .filter(pk=root.pk, active=False, soft_delete_batch__isnull=False)
                .first()
            )
            if stored is None:
                raise NotInRecycleBinError()

            batch = stored.soft_delete_batch
            renamed_from = cls._free_name(stored, resource)
            cls._restore_batch(batch)
            stored.refresh_from_db()

        logger.info(
            "Restored {model} {pk} (batch {batch})",
            model=resource.model.__name__,
            pk=stored.pk,
            batch=batch,
        )
        return RestoreResult(object=stored, renamed_from=renamed_from)

    @staticmethod
    def _free_name(stored: models.Model, resource: BinResource) -> str | None:
        name = getattr(stored, resource.name_field)
        free_name = next_copy_name(
            resource.model,
            org_id=getattr(stored, f"{resource.org_field}_id"),
            base_name=name,
            also_taken=resource.also_taken,
            name_field=resource.name_field,
            org_field=resource.org_field,
        )
        if free_name == name:
            return None
        # A queryset update, not save(): SourceCollection.save() would apply its
        # own "Name (N)" rename on top of this one.
        resource.model.all_objects.filter(pk=stored.pk).update(**{resource.name_field: free_name})
        return name

    @staticmethod
    def _restore_batch(batch) -> None:
        listener_models = []
        for model in _soft_delete_models():
            if post_save.has_listeners(model):
                listener_models.append(model)
                continue
            model.all_objects.filter(soft_delete_batch=batch, active=False).update(
                active=True, soft_deleted_at=None, soft_delete_batch=None
            )

        # After the bulk writes, so a receiver (trigger re-registration) sees its
        # flow already live.
        for model in listener_models:
            for row in model.all_objects.filter(soft_delete_batch=batch, active=False):
                row.active = True
                row.soft_deleted_at = None
                row.soft_delete_batch = None
                row.save(update_fields=_RESTORED_FIELDS)
