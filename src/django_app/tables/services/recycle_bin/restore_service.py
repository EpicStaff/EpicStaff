import uuid
from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from django.apps import apps
from django.db import IntegrityError, models, transaction
from django.db.models.signals import post_save
from loguru import logger
from tables.exceptions import NotInRecycleBinError, RestoreConflictError
from tables.import_export.utils import clean_base_name, slug_base
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
        "#N" name, the same pattern a copy uses. An owned row whose owner is
        still in the bin (a surface deleted with its agent) comes back on its
        own, without its owner: see _detach_from_binned_owner.

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
            if cls._owner_is_binned(stored, resource):
                cls._detach_from_binned_owner(stored, resource)

            batch = stored.soft_delete_batch
            renamed_from = cls._free_names(stored, resource, batch)
            if resource.before_restore is not None:
                resource.before_restore(stored, batch)
            try:
                cls._restore_batch(batch)
            except IntegrityError as error:
                # A live-only unique value (a phone number, a webhook path) was
                # taken after the restore checked it: nothing is restored.
                raise RestoreConflictError() from error
            stored.refresh_from_db()
            if resource.after_restore is not None:
                restored_root = stored
                transaction.on_commit(lambda: resource.after_restore(restored_root))

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
    def _owner_is_binned(stored: models.Model, resource: BinResource) -> bool:
        if resource.owner_field is None:
            return False
        owner_id = getattr(stored, f"{resource.owner_field}_id")
        owner_model = resource.model._meta.get_field(resource.owner_field).related_model
        return (
            owner_id is not None
            and owner_model.all_objects.filter(pk=owner_id, active=False).exists()
        )

    @classmethod
    def _detach_from_binned_owner(cls, stored: models.Model, resource: BinResource) -> None:
        """Restoring an owned row on its own brings it back without its owner.

        Its owner (an agent, for a surface) stays in the bin. Left pointing at it,
        the row would come back attached to a binned owner, and purging the
        owner would delete it for good. So the row and everything that belongs
        to it move to a batch of their own, and the owner link is cleared: the
        row comes back shared. The owner's own links to it (its default-surface
        rows) stay in the owner's batch and come back with the owner.
        """
        new_batch = uuid.uuid4()
        for model, pks in cls._owned_subtree(stored).items():
            model.all_objects.filter(pk__in=pks).update(soft_delete_batch=new_batch)
        resource.model.all_objects.filter(pk=stored.pk).update(
            **{f"{resource.owner_field}_id": None}
        )
        stored.refresh_from_db()

    @staticmethod
    def _owned_subtree(root: models.Model) -> dict[type[models.Model], set]:
        """`root` and the binned rows of its batch that hang under it through owning FKs.

        Reference links (a model's soft_delete_reference_fields, like an agent's
        default-surface row) point at the row without belonging to it, so the
        walk doesn't follow them.
        """
        batch = root.soft_delete_batch
        subtree: dict[type[models.Model], set] = defaultdict(set)
        subtree[type(root)].add(root.pk)
        pending = [(type(root), {root.pk})]
        while pending:
            model, pks = pending.pop()
            for relation in model._meta.get_fields(include_hidden=True):
                if not (relation.one_to_many or relation.one_to_one) or not relation.auto_created:
                    continue
                child_model = relation.related_model
                if not issubclass(child_model, SoftDeleteFields):
                    continue
                if relation.field.name in child_model.soft_delete_reference_fields:
                    continue
                child_pks = (
                    set(
                        child_model.all_objects.filter(
                            **{f"{relation.field.name}__in": pks}, soft_delete_batch=batch
                        ).values_list("pk", flat=True)
                    )
                    - subtree[child_model]
                )
                if child_pks:
                    subtree[child_model] |= child_pks
                    pending.append((child_model, child_pks))
        return subtree

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
                    cls._lock_org(item[1], item[0]),
                    cls._lock_name(item[0], getattr(item[1], item[0].name_field)),
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
    def _lock_name(resource: BinResource, name: str) -> str:
        """The name family next_copy_name locks for `name` (lowercased where case doesn't count)."""
        clean = slug_base(name) if resource.slug_names else clean_base_name(name)
        return clean.lower() if resource.case_insensitive_names else clean

    @staticmethod
    def _lock_org(row: models.Model, resource: BinResource) -> int | None:
        """The org next_copy_name locks for `row`: none for names unique across orgs."""
        return None if resource.global_names else getattr(row, f"{resource.org_field}_id")

    @staticmethod
    def _free_name(stored: models.Model, resource: BinResource, extra_taken_names: set[str]) -> str:
        """Return the name `stored` comes back under, renaming it if that one is taken."""
        name = getattr(stored, resource.name_field)
        if not resource.unique_names:
            return name
        free_name = next_copy_name(
            resource.model,
            org_id=getattr(stored, f"{resource.org_field}_id"),
            base_name=name,
            also_taken=resource.also_taken,
            name_field=resource.name_field,
            org_field=resource.org_field,
            extra_taken_names=extra_taken_names,
            case_insensitive_names=resource.case_insensitive_names,
            slug_names=resource.slug_names,
            global_names=resource.global_names,
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
