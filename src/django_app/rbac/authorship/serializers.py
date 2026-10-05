import datetime
import functools

from rest_framework import serializers

from rbac.authorship.last_edit import (
    LAST_EDIT_STATE_CONTEXT_KEY,
    LAST_EDIT_TRACKER_CONTEXT_KEY,
    LastEditTracker,
    affects_last_edits,
)
from rbac.authorship.policy import AUTHOR_FIELD, has_author_field, resolve_author
from rbac.models.last_edit import ResourceLastEdit

_STAMPING_MARKER = "_stamps_author"
_ACTIVE_TRACKER_ATTRIBUTE = "_active_last_edit_tracker"


class AuthorStampingSerializerMixin:
    """Stamp the author on create, claim ownerless rows on update and record real edits.

    Every subclass has its resolved `get_fields`, `create` and `update` wrapped, so this
    applies whatever the base order; once per outermost call, a last edit is recorded for
    a created or changed resource and for the owner it edited (a node's graph). The acting
    user comes from `context["request"].user`, falling back to a `created_by` passed
    through `serializer.save(created_by=...)`.
    """

    # Serializer whose representation defines the resource state compared for a last
    # edit; None uses this serializer's own representation.
    last_edit_state_serializer_class: type[serializers.BaseSerializer] | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method_name, wrap in (
            ("get_fields", _wrap_get_fields),
            ("create", _wrap_create),
            ("update", _wrap_update),
        ):
            method = getattr(cls, method_name)
            if not getattr(method, _STAMPING_MARKER, False):
                setattr(cls, method_name, wrap(method))

    def _stamp_author_for_create(self, validated_data: dict) -> dict:
        explicit_author = validated_data.pop(AUTHOR_FIELD, None)
        if _has_author_field(getattr(getattr(self, "Meta", None), "model", None)):
            validated_data[AUTHOR_FIELD] = self._resolve_acting_author(explicit_author)
        return validated_data

    def _stamp_author_for_update(self, instance, validated_data: dict) -> dict:
        explicit_author = validated_data.pop(AUTHOR_FIELD, None)
        if _has_author_field(type(instance)) and instance.created_by_id is None:
            author = self._resolve_acting_author(explicit_author)
            if author is not None:
                validated_data[AUTHOR_FIELD] = author
        return validated_data

    def _resolve_acting_author(self, explicit_author):
        request = self.context.get("request")
        return resolve_author(getattr(request, "user", None)) or resolve_author(explicit_author)

    def _last_edit_tracker(self, explicit_author) -> tuple[LastEditTracker | None, bool]:
        """Return the tracker for this write and whether this call owns (finishes) it."""
        shared_tracker = self.context.get(LAST_EDIT_TRACKER_CONTEXT_KEY) or getattr(
            self, _ACTIVE_TRACKER_ATTRIBUTE, None
        )
        if shared_tracker is not None:
            return shared_tracker, False
        request = self.context.get("request")
        if request is not None:
            return LastEditTracker(request.user), True
        if explicit_author is not None:
            return LastEditTracker(explicit_author), True
        return None, False

    def _run_tracked(self, write, explicit_author, watch):
        tracker, owns_tracker = self._last_edit_tracker(explicit_author)
        if tracker is None:
            return write()
        if not owns_tracker:
            return watch(tracker, write)
        setattr(self, _ACTIVE_TRACKER_ATTRIBUTE, tracker)
        try:
            instance = watch(tracker, write)
        finally:
            delattr(self, _ACTIVE_TRACKER_ATTRIBUTE)
        tracker.finish()
        return instance


class LastEditFieldsSerializerMixin:
    """Expose the resource's last edit as read-only `last_edited_by` and `last_edited_at`.

    Both come from one read of `instance.last_edits.all()` per rendered instance, so a
    queryset that prefetches `last_edits` adds no query per row. Comparison state for
    change detection is rendered without them.
    """

    def get_fields(self):
        fields = super().get_fields()
        if not self.context.get(LAST_EDIT_STATE_CONTEXT_KEY):
            fields["last_edited_by"] = serializers.SerializerMethodField()
            fields["last_edited_at"] = serializers.SerializerMethodField()
        return fields

    def to_representation(self, instance):
        self._rendered_last_edit = None
        return super().to_representation(instance)

    def get_last_edited_by(self, instance) -> int | None:
        last_edit = self._last_edit_being_rendered(instance)
        return last_edit.edited_by_id if last_edit is not None else None

    def get_last_edited_at(self, instance) -> str | None:
        last_edit = self._last_edit_being_rendered(instance)
        return represent_last_edited_at(last_edit.edited_at if last_edit is not None else None)

    def _last_edit_being_rendered(self, instance) -> ResourceLastEdit | None:
        # Keyed by the instance itself: a subclass whose to_representation() skips
        # super() must still never be served another row's last edit.
        rendered = getattr(self, "_rendered_last_edit", None)
        if rendered is None or rendered[0] is not instance:
            rendered = (instance, next(iter(instance.last_edits.all()), None))
            self._rendered_last_edit = rendered
        return rendered[1]


def represent_last_edited_at(edited_at: datetime.datetime | None) -> str | None:
    """Render `edited_at` the way every API response renders `last_edited_at`."""
    if edited_at is None:
        return None
    return serializers.DateTimeField().to_representation(edited_at)


def _has_author_field(model) -> bool:
    # Plain serializers have no model; they hand validated_data to a service
    # that creates the row, so the author key is passed through.
    return model is None or has_author_field(model)


def _mark_stamping(wrapper):
    setattr(wrapper, _STAMPING_MARKER, True)
    return wrapper


# Stamping is idempotent: a wrapped body that calls super() into another wrapped
# method stamps the same author twice. Last-edit tracking shares one tracker across
# nested wrapped calls, so the outermost call records once.
def _wrap_get_fields(get_fields):
    @functools.wraps(get_fields)
    def stamped_get_fields(self):
        fields = get_fields(self)
        if AUTHOR_FIELD in fields:
            fields[AUTHOR_FIELD].read_only = True
        return fields

    return _mark_stamping(stamped_get_fields)


def _wrap_create(create):
    @functools.wraps(create)
    def stamped_create(self, validated_data):
        explicit_author = validated_data.get(AUTHOR_FIELD)
        validated_data = self._stamp_author_for_create(validated_data)

        def watch_created(tracker, write):
            instance = write()
            if affects_last_edits(instance):
                tracker.watch_create(self, instance)
            return instance

        return self._run_tracked(
            lambda: create(self, validated_data), explicit_author, watch_created
        )

    return _mark_stamping(stamped_create)


def _wrap_update(update):
    @functools.wraps(update)
    def stamped_update(self, instance, validated_data):
        explicit_author = validated_data.get(AUTHOR_FIELD)
        validated_data = self._stamp_author_for_update(instance, validated_data)

        def watch_updated(tracker, write):
            if affects_last_edits(instance):
                tracker.watch_update(self, instance)
            return write()

        return self._run_tracked(
            lambda: update(self, instance, validated_data), explicit_author, watch_updated
        )

    return _mark_stamping(stamped_update)
