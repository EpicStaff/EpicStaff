import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from rest_framework import serializers

from rbac.authorship.policy import resolve_author
from rbac.models.last_edit import LastEditTrackedModel, ResourceLastEdit

LAST_EDIT_TRACKER_CONTEXT_KEY = "last_edit_tracker"
# Set in a serializer context to render without authorship: `created_by` stays its
# plain id and `last_edited_by`/`last_edited_at` are left out, so rendering reads no
# user and no last edit. Propagates to nested serializers. Used for change-detection
# state and for payloads no person reads (surface combining, internal service lookups).
OMIT_AUTHORSHIP_CONTEXT_KEY = "omit_authorship"

# Keys a write changes without the resource's own state changing: timestamps,
# authorship, the optimistic-lock hash and the graph save counter.
VOLATILE_REPRESENTATION_KEYS = frozenset(
    {
        "updated_at",
        "content_hash",
        "last_edited_by",
        "last_edited_at",
        "created_by",
        "created_at",
        "save_version",
    }
)
_CHILD_ROW_ID_KEY = "id"

# (owner model, owner primary key) of the resource an edit of a row also edits.
OwnerReference = tuple[type[models.Model], Any]


def record_last_edit(
    instance: LastEditTrackedModel,
    user: object | None,
    *,
    edited_at: datetime.datetime | None = None,
) -> None:
    """Record `user` as the last editor of `instance` at `edited_at` (default: now)."""
    record_last_edits([instance], user, edited_at=edited_at)


def record_last_edits(
    instances: Iterable[LastEditTrackedModel],
    user: object | None,
    *,
    edited_at: datetime.datetime | None = None,
) -> None:
    """Upsert the last edit of every instance in one statement.

    Does nothing when `user` is None (no acting user). A user that does not resolve to an
    author, such as the system API-key principal, is recorded as a NULL editor; rows that
    opt out via `records_last_edit()` are skipped. Never sets `created_by`: an edit does
    not make the editor the author.
    """
    if user is None:
        return
    editor = resolve_author(user)
    edited_at = edited_at or timezone.now()
    _upsert(
        RecordedLastEdit(instance, editor.pk if editor else None, edited_at)
        for instance in instances
    )


@dataclass(frozen=True)
class RecordedLastEdit:
    """A last edit to write exactly as recorded earlier, e.g. in a graph version."""

    resource: LastEditTrackedModel
    edited_by_id: int | None
    edited_at: datetime.datetime


def restore_last_edits(recorded: Iterable[RecordedLastEdit]) -> None:
    """Upsert each resource's recorded editor and time in one statement.

    The caller decides whether a recorded editor may still be shown. Rows that opt out
    via `records_last_edit()` are skipped.
    """
    _upsert(recorded)


def _upsert(recorded: Iterable[RecordedLastEdit]) -> None:
    rows: dict[tuple[int, Any], ResourceLastEdit] = {}
    for entry in recorded:
        if not entry.resource.records_last_edit():
            continue
        content_type = ContentType.objects.get_for_model(entry.resource)
        rows[(content_type.pk, entry.resource.pk)] = ResourceLastEdit(
            content_type=content_type,
            object_id=entry.resource.pk,
            edited_by_id=entry.edited_by_id,
            edited_at=entry.edited_at,
        )
    if not rows:
        return
    ResourceLastEdit.objects.bulk_create(
        rows.values(),
        update_conflicts=True,
        unique_fields=["content_type", "object_id"],
        update_fields=["edited_by", "edited_at"],
    )


@dataclass
class _WatchedWrite:
    instance: models.Model
    state_serializer: serializers.BaseSerializer | None = None
    state_before: dict | None = None
    owner_before: OwnerReference | None = None


class LastEditTracker:
    """Find the resources a set of writes really changed and record their last edit.

    A write that nests child rows outside `serializer.update()` passes one tracker in the
    serializer context under `LAST_EDIT_TRACKER_CONTEXT_KEY` and calls `finish()` after
    its last write. Models declare `last_edit_owner_field` (the FK to the resource their
    edits also edit) and `last_edit_canvas_fields` (canvas field -> keys that edit the
    owner; never an edit of the row itself).
    """

    def __init__(self, user: object):
        self._user = user
        self._watched: dict[tuple[type[models.Model], Any], _WatchedWrite] = {}
        self._edited_owner_references: set[OwnerReference] = set()
        self._marked_edited: list[LastEditTrackedModel] = []

    def watch_update(self, serializer: serializers.BaseSerializer, instance: models.Model) -> None:
        """Remember the state of `instance` before its first write in this tracker."""
        key = _identity(instance)
        if key not in self._watched:
            state_serializer = _state_serializer_for(serializer)
            self._watched[key] = _WatchedWrite(
                instance,
                state_serializer,
                _comparable_state(state_serializer, instance),
                _owner_reference(instance),
            )

    def watch_create(self, serializer: serializers.BaseSerializer, instance: models.Model) -> None:
        """Remember that `instance` was created; a creation edits it and its owner."""
        self._watched.setdefault(_identity(instance), _WatchedWrite(instance))

    def watch_delete(self, instance: models.Model) -> None:
        """Remember that `instance` is being deleted; a deletion edits its owner."""
        self._add_owner_reference(_owner_reference(instance))

    def mark_edited(self, resource: LastEditTrackedModel) -> None:
        """Record `resource` as edited by a write this tracker did not watch."""
        self._marked_edited.append(resource)

    def finish(self) -> None:
        """Compare every watched update with its current state and record the edited resources.

        Edited rows, the owners they edited and the rows marked edited are recorded in one
        statement.
        """
        edited = []
        for watched in self._watched.values():
            if watched.state_serializer is None:
                edited.append(watched.instance)
                self._add_owner_reference(_owner_reference(watched.instance))
                continue
            _reload(watched.instance)
            state_after = _comparable_state(watched.state_serializer, watched.instance)
            canvas_fields = getattr(watched.instance, "last_edit_canvas_fields", {})
            if _owner_view(state_after, canvas_fields) != _owner_view(
                watched.state_before, canvas_fields
            ):
                self._add_owner_reference(watched.owner_before)
                self._add_owner_reference(_owner_reference(watched.instance))
            if _without(state_after, canvas_fields) != _without(
                watched.state_before, canvas_fields
            ):
                edited.append(watched.instance)
        edited.extend(self._marked_edited)
        edited.extend(_load_owners(self._edited_owner_references, known=edited))
        self._watched.clear()
        self._edited_owner_references.clear()
        self._marked_edited.clear()
        record_last_edits(
            [instance for instance in edited if isinstance(instance, LastEditTrackedModel)],
            self._user,
        )

    def _add_owner_reference(self, reference: OwnerReference | None) -> None:
        if reference is not None:
            self._edited_owner_references.add(reference)


def affects_last_edits(instance: models.Model) -> bool:
    """Return whether a write of `instance` can record a last edit, for itself or its owner."""
    return isinstance(instance, LastEditTrackedModel) or _owner_reference(instance) is not None


def _owner_reference(instance: models.Model) -> OwnerReference | None:
    owner_field_name = getattr(instance, "last_edit_owner_field", None)
    if owner_field_name is None:
        return None
    owner_field = instance._meta.get_field(owner_field_name)
    owner_id = getattr(instance, owner_field.attname)
    if owner_id is None:
        return None
    return owner_field.related_model._meta.concrete_model, owner_id


def _load_owners(
    references: set[OwnerReference], *, known: list[models.Model]
) -> list[models.Model]:
    known_identities = {_identity(instance) for instance in known}
    ids_by_model: dict[type[models.Model], set[Any]] = defaultdict(set)
    for model, owner_id in references - known_identities:
        ids_by_model[model].add(owner_id)
    return [
        owner
        for model, owner_ids in ids_by_model.items()
        for owner in model._base_manager.in_bulk(owner_ids).values()
    ]


def _identity(instance: models.Model) -> tuple[type[models.Model], Any]:
    return instance._meta.concrete_model, instance.pk


def _reload(instance: models.Model) -> None:
    # Writes made after the instance was loaded (QuerySet.update(), child rows) are
    # not in memory; the representation must read the persisted state.
    instance.refresh_from_db()
    if hasattr(instance, "_prefetched_objects_cache"):
        instance._prefetched_objects_cache = {}
    instance._state.fields_cache = {}


def _state_serializer_for(serializer: serializers.BaseSerializer) -> serializers.BaseSerializer:
    state_serializer_class = getattr(serializer, "last_edit_state_serializer_class", None) or type(
        serializer
    )
    return state_serializer_class(context={**serializer.context, OMIT_AUTHORSHIP_CONTEXT_KEY: True})


def _comparable_state(state_serializer: serializers.BaseSerializer, instance: models.Model) -> dict:
    return _normalize(
        state_serializer.to_representation(instance), state_serializer.fields, nested=False
    )


def _normalize(value: Any, fields: Mapping | None, *, nested: bool) -> Any:
    if isinstance(value, list):
        return [_normalize(item, fields, nested=nested) for item in value]
    if not isinstance(value, Mapping):
        return value
    normalized = {}
    for key, item in value.items():
        field = fields.get(key) if fields is not None else None
        if key in VOLATILE_REPRESENTATION_KEYS:
            continue
        # A child row's own id and its read-only link to the owner are assigned by the
        # server, so recreating an unchanged child row is not an edit.
        if nested and (key == _CHILD_ROW_ID_KEY or _is_owner_reference(field)):
            continue
        # Nested serializers and keys added by to_representation() hold child rows;
        # any other field's value (JSON included) is compared as a whole.
        if field is None or isinstance(field, serializers.BaseSerializer):
            normalized[key] = _normalize(item, _nested_fields(field), nested=True)
        else:
            normalized[key] = item
    return normalized


def _is_owner_reference(field: serializers.Field | None) -> bool:
    return isinstance(field, serializers.RelatedField) and field.read_only


def _nested_fields(field: serializers.Field | None) -> Mapping | None:
    if isinstance(field, serializers.ListSerializer):
        field = field.child
    if isinstance(field, serializers.Serializer):
        return field.fields
    return None


def _without(state: dict, keys: Iterable[str]) -> dict:
    return {key: value for key, value in state.items() if key not in keys}


def _owner_view(state: dict, canvas_fields: Mapping[str, tuple[str, ...]]) -> dict:
    return {
        key: _pick(value, canvas_fields[key]) if key in canvas_fields else value
        for key, value in state.items()
    }


def _pick(value: Any, keys: tuple[str, ...]) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    return {key: value[key] for key in keys if key in value}
