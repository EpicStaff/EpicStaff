from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import models, transaction
from django.db.models.deletion import (
    ProtectedError,
    RestrictedError,
)
from django.db.models.signals import post_save
from django.utils import timezone

from tables.models.base_models import SoftDeleteFields


class DeleteService:
    """
    Centralized deletion service.

    Rules (in priority order):

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

    SoftDeleteFields (any other on_delete: CASCADE, DO_NOTHING, or an
    unrecognized value)
        -> soft delete

    Normal model + CASCADE
        -> hard delete

    Normal model + DO_NOTHING
        -> ImproperlyConfigured

    An explicit PROTECT/RESTRICT/SET_NULL/SET_DEFAULT/SET(...) on the FK
    is a stronger, deliberate signal than "this model happens to support
    soft deletion" and always wins. SoftDeleteFields only overrides the
    default hard-delete/CASCADE behavior. A model with a post_save
    receiver also wins over SoftDeleteFields batching, since it must be
    soft-deleted per-object so that signal still fires.

    M2M:
        implicit through
            -> delete only relationship rows

        explicit through
            -> process through model normally
    """

    @classmethod
    def delete(
        cls,
        obj: models.Model,
        using: str | None = None,
    ):
        with transaction.atomic(using=using):
            context = _DeleteContext(using=using)
            context.delete(obj)


class _DeleteContext:
    # on_delete sentinels whose action is an explicit, deterministic
    # developer choice. These always take priority over SoftDeleteFields.
    _PRIORITY_ON_DELETE = frozenset(
        {
            models.PROTECT,
            models.RESTRICT,
            models.SET_NULL,
            models.SET_DEFAULT,
        }
    )

    # Single source of truth mapping an on_delete sentinel to its handler.
    # SET(...) is deliberately not here: it isn't a fixed sentinel, it's a
    # callable produced per-field, so it's detected via _is_set_callable.
    _ON_DELETE_HANDLERS = {
        models.PROTECT: "_handle_protect",
        models.RESTRICT: "_handle_restrict",
        models.SET_NULL: "_handle_set_null",
        models.SET_DEFAULT: "_handle_set_default",
        models.CASCADE: "_handle_cascade",
        models.DO_NOTHING: "_handle_do_nothing",
    }

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

    # Hidden CASCADE relations to SoftDeleteFields children will now be
    # caught by _batch_soft_delete_cascade. This is correct: the batch
    # path respects SoftDeleteFields and visited-set cycle guards exactly
    # as delete() does.
    def _process_reverse_relations(
        self,
        obj: models.Model,
    ):
        for relation in self._get_reverse_relations(obj):
            children = self._get_related_objects(
                obj,
                relation,
            )

            if self._is_soft_delete_cascade_relation(relation):
                self._batch_soft_delete_cascade(children)
                continue

            for child in children:
                self._process_related_object(
                    parent=obj,
                    child=child,
                    relation=relation,
                )

    @staticmethod
    def _get_reverse_relations(obj):
        """
        Yield every reverse FK/OneToOne relation of `obj`, including
        hidden ones (related_name="+"). Hidden relations have no reverse
        accessor, so _get_related_objects fetches their children through
        a direct queryset filter instead of getattr(obj, accessor).
        """
        for relation in obj._meta.get_fields(include_hidden=True):
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
        if relation.hidden:
            queryset = relation.related_model._default_manager.filter(
                **{relation.field.name: obj}
            )

            if relation.one_to_one:
                return list(queryset[:1])

            return queryset

        accessor = relation.get_accessor_name()

        if relation.one_to_one:
            try:
                return [getattr(obj, accessor)]
            except relation.related_model.DoesNotExist:
                return []

        manager = getattr(obj, accessor)

        return manager.all()

    # ==========================================================
    # Relation-level CASCADE / SoftDeleteFields batching
    # ==========================================================

    @classmethod
    def _is_soft_delete_cascade_relation(cls, relation) -> bool:
        """
        True when every child reachable through this reverse relation
        will be soft-deleted via CASCADE semantics.

        All children of a single reverse relation share the same
        concrete model class and the same FK's on_delete behavior, so
        this verdict is decided once per relation instead of once per
        child object — that's what makes batching the terminal write
        possible.

        An explicit PROTECT/RESTRICT/SET_NULL/SET_DEFAULT/SET(...) on the
        FK always wins over SoftDeleteFields, matching
        _process_related_object's priority order.
        """
        field = relation.field
        on_delete = field.remote_field.on_delete

        if on_delete in cls._PRIORITY_ON_DELETE:
            return False

        if cls._is_set_callable(on_delete):
            return False

        # A model with a post_save receiver relies on that signal firing
        # per-object (e.g. schedule/webhook/telegram trigger nodes publish
        # a Redis event for the Manager service on every save).
        # QuerySet.update() never triggers post_save, so such models must
        # go through the per-object path instead of the batched UPDATE.
        if post_save.has_listeners(field.model):
            return False

        return issubclass(field.model, SoftDeleteFields)

    def _batch_soft_delete_cascade(self, children):
        """
        Soft-delete every child of a single reverse relation with one
        UPDATE instead of one .save() per object.

        Recursion and cycle-safety are preserved exactly: each child's
        own reverse/M2M relations are still walked first (so
        grandchildren are fully processed before this relation's batch
        write goes out), and the visited-set guard is still applied per
        object, before it is touched at all, exactly as delete() does
        for the non-batched path. Only the terminal
        is_soft_deleted/soft_deleted_at write is batched.

        Children are grouped by their actual class before the write:
        a single reverse relation is expected to yield children of one
        concrete model, but that is only an assumption documented on
        _is_soft_delete_cascade_relation, never enforced here. Grouping
        by type(child) means a heterogeneous `children` iterable still
        produces one correct UPDATE per model instead of silently
        mixing unrelated PKs into a single query against one class.
        """
        pks_to_soft_delete_by_model: dict[type[models.Model], list[Any]] = defaultdict(
            list
        )

        for child in children:
            key = self._get_key(child)

            if key in self.visited:
                continue

            self.visited.add(key)

            # Descend into this child's own reverse/M2M relations before
            # closing it off with the batched write below — identical
            # ordering to delete()'s single-object recursive path.
            self._process_reverse_relations(child)
            self._process_m2m_relations(child)

            if child.is_soft_deleted:
                continue

            pks_to_soft_delete_by_model[type(child)].append(child.pk)

        for model_class, pks_to_soft_delete in pks_to_soft_delete_by_model.items():
            # all_objects (unfiltered) rather than the model's default
            # manager: we need to reach every collected pk regardless of
            # which manager ends up being the model's default.
            model_class.all_objects.using(self.using).filter(
                pk__in=pks_to_soft_delete,
                is_soft_deleted=False,
            ).update(
                is_soft_deleted=True,
                soft_deleted_at=timezone.now(),
            )

    # ==========================================================
    # Related object processing (non-SoftDeleteFields-CASCADE paths)
    # ==========================================================

    def _process_related_object(
        self,
        parent: models.Model,
        child: models.Model,
        relation,
    ):
        """
        Process a single dependent object for relations where
        _is_soft_delete_cascade_relation returned False — i.e. an
        explicit PROTECT/RESTRICT/SET_NULL/SET_DEFAULT/SET(...), a plain
        (non-SoftDeleteFields) model under CASCADE/DO_NOTHING/an
        unrecognized on_delete, or a SoftDeleteFields model that was
        excluded from batching solely because it has a post_save
        listener.
        """

        field = relation.field
        on_delete = field.remote_field.on_delete

        # ------------------------------------------------------
        # PROTECT / RESTRICT / SET_NULL / SET_DEFAULT
        # ------------------------------------------------------
        # These always take priority, even if a later check (e.g. the
        # nullable-fallback below) could also apply.

        if on_delete in self._PRIORITY_ON_DELETE:
            handler = getattr(self, self._ON_DELETE_HANDLERS[on_delete])
            return handler(parent, child, field)

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
        # Only for plain (non-SoftDeleteFields) models: a SoftDeleteFields
        # child that reached this method did so only because a post_save
        # listener excluded it from batching (see
        # _is_soft_delete_cascade_relation), not because CASCADE onto it
        # should be treated as a nullable-fallback like Session.graph.
        # It must still fall through to the CASCADE handler below so it
        # gets soft-deleted (and its post_save receiver fires), instead of
        # having its FK silently nulled out.

        if field.null and not issubclass(field.model, SoftDeleteFields):
            self._set_null(
                child,
                field,
            )
            return

        # ------------------------------------------------------
        # DO_NOTHING / CASCADE
        # ------------------------------------------------------

        handler_name = self._ON_DELETE_HANDLERS.get(on_delete)
        if handler_name is not None:
            handler = getattr(self, handler_name)
            return handler(parent, child, field)

        raise ImproperlyConfigured(f"Unsupported on_delete behavior: {on_delete!r}")

    # ==========================================================
    # on_delete handlers
    # ==========================================================

    def _handle_protect(self, parent, child, field):
        raise ProtectedError(
            "Cannot delete object because a related object uses PROTECT.",
            [parent],
        )

    def _handle_restrict(self, parent, child, field):
        raise RestrictedError(
            "Cannot delete object because a related object uses RESTRICT.",
            [parent],
        )

    def _handle_set_null(self, parent, child, field):
        self._set_null(child, field)

    def _handle_set_default(self, parent, child, field):
        self._set_default(child, field)

    def _handle_cascade(self, parent, child, field):
        self.delete(child)

    def _handle_do_nothing(self, parent, child, field):
        raise ImproperlyConfigured(
            f"{child.__class__.__name__}.{field.name} "
            "uses DO_NOTHING. DeleteService cannot "
            "guarantee referential integrity."
        )

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
                f"{obj.__class__.__name__}.{field.name} uses SET_NULL but null=False."
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
        for relation in obj._meta.get_fields(include_hidden=True):
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
