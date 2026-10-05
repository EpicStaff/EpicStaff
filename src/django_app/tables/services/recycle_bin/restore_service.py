from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from django.apps import apps
from django.db import models, transaction
from django.db.models.signals import post_save
from loguru import logger
from tables.exceptions import NotInRecycleBinError, OwnerInRecycleBinError
from tables.import_export.utils import clean_base_name
from tables.models.base_models import SoftDeleteFields
from tables.services.copy_services.helpers import name_lock_key, next_copy_name
from tables.services.recycle_bin.registry import BinResource, bin_resource_for, bin_resources

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
            cls._lock_owner(root, resource)
            stored = (
                resource.model.all_objects.select_for_update()
                .filter(pk=root.pk, active=False, soft_delete_batch__isnull=False)
                .first()
            )
            if stored is None:
                raise NotInRecycleBinError()
            # The owner was read before the root was locked; lock it again in case
            # the row was reassigned to another owner meanwhile.
            cls._lock_owner(stored, resource)
            cls._refuse_if_owner_is_binned(stored, resource)

            batch = stored.soft_delete_batch
            renamed_from = cls._free_names(stored, resource, batch)
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
    def _lock_owner(owned: models.Model, resource: BinResource) -> None:
        """Lock the owner row of `owned` (before `owned` itself, on the first call).

        A delete of the owner locks the owner first and then walks into its owned
        rows, so taking the locks in that same order means a restore and a
        parallel delete of the owner run one after the other, and the owner check
        sees the committed state. `no_key` still conflicts with that delete but
        doesn't block unrelated inserts that point at the owner.
        """
        if resource.owner_field is None:
            return
        owner_id = (
            resource.model.all_objects.filter(pk=owned.pk)
            .values_list(f"{resource.owner_field}_id", flat=True)
            .first()
        )
        if owner_id is not None:
            owner_model = resource.model._meta.get_field(resource.owner_field).related_model
            list(
                owner_model.all_objects.select_for_update(no_key=True)
                .filter(pk=owner_id)
                .values_list("pk", flat=True)
            )

    @staticmethod
    def _refuse_if_owner_is_binned(stored: models.Model, resource: BinResource) -> None:
        """An owned row whose owner is binned would come back pointing at it, and
        a later purge of the owner would delete it for good with no bin."""
        if resource.owner_field is None:
            return
        owner_id = getattr(stored, f"{resource.owner_field}_id")
        owner_model = resource.model._meta.get_field(resource.owner_field).related_model
        if (
            owner_id is not None
            and owner_model.all_objects.filter(pk=owner_id, active=False).exists()
        ):
            raise OwnerInRecycleBinError()

    @classmethod
    def _free_names(cls, stored: models.Model, resource: BinResource, batch) -> str | None:
        """Free the name of every named row the restore brings back.

        Not only the root: an agent's owned surfaces come back with it, and a
        surface created meanwhile under one of their names would block the
        restore. Returns the root's old name when it was renamed.
        """
        named_rows = [(resource, stored)]
        for other_resource in bin_resources().values():
            rows = other_resource.model.all_objects.filter(soft_delete_batch=batch, active=False)
            if other_resource.model is resource.model:
                rows = rows.exclude(pk=stored.pk)
            named_rows += [(other_resource, row) for row in rows]
        # next_copy_name locks each (org, name family). Sorting by that same lock
        # key means every restore takes its locks in one order, so two can't deadlock.
        named_rows.sort(
            key=lambda item: (
                name_lock_key(
                    getattr(item[1], f"{item[0].org_field}_id"),
                    clean_base_name(getattr(item[1], item[0].name_field)),
                ),
                item[0].model._meta.label,
                item[1].pk,
            )
        )
        # The names each (model, org) will hold once the batch is live: a rename
        # must not land on a name another row of this same restore brings back.
        names_after_restore: defaultdict[tuple, set[str]] = defaultdict(set)
        for row_resource, row in named_rows:
            names_after_restore[cls._name_scope(row, row_resource)].add(
                getattr(row, row_resource.name_field)
            )

        renamed_from = None
        for row_resource, row in named_rows:
            scope = cls._name_scope(row, row_resource)
            old_name = getattr(row, row_resource.name_field)
            names_after_restore[scope].discard(old_name)
            new_name = cls._free_name(
                row, row_resource, extra_taken_names=names_after_restore[scope]
            )
            names_after_restore[scope].add(new_name)
            if row is stored and new_name != old_name:
                renamed_from = old_name
        return renamed_from

    @staticmethod
    def _name_scope(row: models.Model, resource: BinResource) -> tuple:
        return (resource.model, getattr(row, f"{resource.org_field}_id"))

    @staticmethod
    def _free_name(stored: models.Model, resource: BinResource, extra_taken_names: set[str]) -> str:
        """Return the name `stored` comes back under, renaming it if that one is taken."""
        name = getattr(stored, resource.name_field)
        free_name = next_copy_name(
            resource.model,
            org_id=getattr(stored, f"{resource.org_field}_id"),
            base_name=name,
            also_taken=resource.also_taken,
            name_field=resource.name_field,
            org_field=resource.org_field,
            extra_taken_names=extra_taken_names,
        )
        if free_name != name:
            # A queryset update, not save(): SourceCollection.save() would apply
            # its own "Name (N)" rename on top of this one.
            resource.model.all_objects.filter(pk=stored.pk).update(
                **{resource.name_field: free_name}
            )
        return free_name

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
