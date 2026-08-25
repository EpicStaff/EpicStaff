from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import models, transaction
from django.db.models.deletion import (
    ProtectedError,
    RestrictedError,
)
from django.utils import timezone

from tables.models.base_models import SoftDeleteFields


class DeleteService:
    """
    Centralized deletion service.

    Rules:

    SoftDeleteFields
        -> soft delete

    Normal model + PROTECT
        -> ProtectedError

    Normal model + RESTRICT
        -> RestrictedError

    Normal model + SET_NULL
        -> set FK to NULL

    Normal model + SET_DEFAULT
        -> set FK to default

    Normal model + SET(...)
        -> set FK to specified value

    Normal model + CASCADE
        -> hard delete

    Normal model + DO_NOTHING
        -> ImproperlyConfigured

    M2M:
        implicit through
            -> delete only relationship rows

        explicit through
            -> process through model normally
    """

    @classmethod
    @transaction.atomic
    def delete(
        cls,
        obj: models.Model,
        using: str | None = None,
    ):
        context = _DeleteContext(using=using)
        context.delete(obj)


class _DeleteContext:
    def __init__(self, using: str | None = None):
        self.using = using
        self.visited: set[tuple[type[models.Model], Any]] = set()

    # ==========================================================
    # Main entry point
    # ==========================================================

    def delete(self, obj: models.Model):
        key = self._get_key(obj)

        if key in self.visited:
            return

        self.visited.add(key)

        # Process relations first.
        self._process_reverse_relations(obj)
        self._process_m2m_relations(obj)

        # Then process the object itself.
        self._delete_object(obj)

    # ==========================================================
    # Object deletion
    # ==========================================================

    def _delete_object(self, obj: models.Model):
        if isinstance(obj, SoftDeleteFields):
            self._soft_delete(obj)
        else:
            self._hard_delete(obj)

    def _soft_delete(self, obj: SoftDeleteFields):
        if obj.is_soft_deleted:
            return

        obj.is_soft_deleted = True
        obj.soft_deleted_at = timezone.now()

        obj.save(
            update_fields=[
                "is_soft_deleted",
                "soft_deleted_at",
            ],
            using=self.using,
        )

    def _hard_delete(self, obj: models.Model):
        """
        Physical deletion.

        We deliberately call Django's Model.delete(),
        not obj.delete(), because obj.delete() may be
        overridden by SoftDeleteFields.
        """

        models.Model.delete(
            obj,
            using=self.using,
        )

    # ==========================================================
    # Reverse FK / OneToOne
    # ==========================================================

    def _process_reverse_relations(
        self,
        obj: models.Model,
    ):
        for relation in self._get_reverse_relations(obj):
            children = self._get_related_objects(
                obj,
                relation,
            )

            for child in children:
                self._process_related_object(
                    parent=obj,
                    child=child,
                    relation=relation,
                )

    @staticmethod
    def _get_reverse_relations(obj):
        for relation in obj._meta.get_fields():
            if not relation.auto_created:
                continue

            if not relation.is_relation:
                continue

            # M2M is handled separately.
            if relation.many_to_many:
                continue

            if not (relation.one_to_many or relation.one_to_one):
                continue

            yield relation

    @staticmethod
    def _get_related_objects(
        obj,
        relation,
    ):
        accessor = relation.get_accessor_name()

        if relation.one_to_one:
            try:
                return [getattr(obj, accessor)]
            except relation.related_model.DoesNotExist:
                return []

        manager = getattr(obj, accessor)

        return manager.all()

    # ==========================================================
    # Related object processing
    # ==========================================================

    def _process_related_object(
        self,
        parent: models.Model,
        child: models.Model,
        relation,
    ):
        """
        Process a direct dependent object.

        The important rule is:

        SoftDeleteFields always wins.

        We do not care whether its FK says CASCADE,
        SET_NULL, PROTECT, etc. If the dependent object
        itself supports soft deletion, it gets soft-deleted.
        """

        if isinstance(child, SoftDeleteFields):
            self.delete(child)
            return

        field = relation.field

        on_delete = field.remote_field.on_delete

        # ------------------------------------------------------
        # PROTECT
        # ------------------------------------------------------

        if on_delete is models.PROTECT:
            raise ProtectedError(
                "Cannot delete object because " "a related object uses PROTECT.",
                [parent],
            )

        # ------------------------------------------------------
        # RESTRICT
        # ------------------------------------------------------

        if on_delete is models.RESTRICT:
            raise RestrictedError(
                "Cannot delete object because " "a related object uses RESTRICT.",
                [parent],
            )

        # ------------------------------------------------------
        # SET_NULL
        # ------------------------------------------------------

        if on_delete is models.SET_NULL:
            self._set_null(
                child,
                field,
            )
            return

        # ------------------------------------------------------
        # SET_DEFAULT
        # ------------------------------------------------------

        if on_delete is models.SET_DEFAULT:
            self._set_default(
                child,
                field,
            )
            return

        # ------------------------------------------------------
        # SET(...)
        # ------------------------------------------------------

        if self._is_set_callable(on_delete):
            self._set_custom_value(
                child,
                field,
                on_delete,
            )
            return
        # ------------------------------------------------------
        # SET_NULL if it is possible
        # ------------------------------------------------------

        if field.null:
            self._set_null(
                child,
                field,
            )
            return
        # ------------------------------------------------------
        # DO_NOTHING
        # ------------------------------------------------------

        if on_delete is models.DO_NOTHING:
            raise ImproperlyConfigured(
                f"{child.__class__.__name__}.{field.name} "
                "uses DO_NOTHING. DeleteService cannot "
                "guarantee referential integrity."
            )

        # ------------------------------------------------------
        # CASCADE
        # ------------------------------------------------------

        if on_delete is models.CASCADE:
            self.delete(child)
            return

        raise ImproperlyConfigured(f"Unsupported on_delete behavior: {on_delete!r}")

    # ==========================================================
    # SET_NULL
    # ==========================================================

    def _set_null(
        self,
        obj: models.Model,
        field,
    ):
        if not field.null:
            raise ImproperlyConfigured(
                f"{obj.__class__.__name__}.{field.name} "
                "uses SET_NULL but null=False."
            )

        setattr(
            obj,
            field.attname,
            None,
        )

        obj.save(
            update_fields=[field.attname],
            using=self.using,
        )

    # ==========================================================
    # SET_DEFAULT
    # ==========================================================

    def _set_default(
        self,
        obj: models.Model,
        field,
    ):
        value = field.get_default()

        setattr(
            obj,
            field.attname,
            value,
        )

        obj.save(
            update_fields=[field.attname],
            using=self.using,
        )

    # ==========================================================
    # SET(...)
    # ==========================================================

    @staticmethod
    def _is_set_callable(on_delete):
        if not callable(on_delete):
            return False

        deconstruct = getattr(on_delete, "deconstruct", None)

        if deconstruct is None:
            return False

        path, args, kwargs = deconstruct()

        return path == "django.db.models.SET"

    def _set_custom_value(
        self,
        obj: models.Model,
        field,
        on_delete,
    ):
        value = on_delete(field, obj)

        setattr(
            obj,
            field.attname,
            value,
        )

        obj.save(
            update_fields=[field.attname],
            using=self.using,
        )

    # ==========================================================
    # M2M
    # ==========================================================

    def _process_m2m_relations(
        self,
        obj: models.Model,
    ):
        """
        M2M deletion only removes relationship rows.

        The other side of the M2M is NOT deleted.
        """

        # Forward M2M fields.
        for field in obj._meta.many_to_many:
            self._clear_m2m(obj, field)

        # Reverse M2M fields.
        for relation in obj._meta.get_fields():
            if not relation.auto_created:
                continue

            if not relation.many_to_many:
                continue

            self._clear_reverse_m2m(
                obj,
                relation,
            )

    @staticmethod
    def _clear_m2m(
        obj,
        field,
    ):
        manager = getattr(
            obj,
            field.name,
        )

        manager.clear()

    @staticmethod
    def _clear_reverse_m2m(
        obj,
        relation,
    ):
        """
        Remove reverse M2M rows without deleting
        objects on the other side.
        """

        manager = getattr(
            obj,
            relation.get_accessor_name(),
        )

        manager.clear()

    # ==========================================================
    # Helpers
    # ==========================================================

    @staticmethod
    def _get_key(obj):
        return (
            obj.__class__,
            obj.pk,
        )
