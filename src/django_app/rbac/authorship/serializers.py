import functools

from django.core.exceptions import FieldDoesNotExist

from rbac.authorship.policy import resolve_author

AUTHOR_FIELD = "created_by"
_STAMPING_MARKER = "_stamps_author"


class AuthorStampingSerializerMixin:
    """Stamp the acting user as author on create and claim ownerless rows on update.

    Every subclass has its resolved `get_fields`, `create` and `update` wrapped, so
    stamping applies whatever the base order and whether or not a class body defines
    them. The acting user comes from `context["request"].user`, falling back to a
    `created_by` passed through `serializer.save(created_by=...)`.
    """

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


def _has_author_field(model) -> bool:
    # Plain serializers have no model; they hand validated_data to a service
    # that creates the row, so the author key is passed through.
    if model is None:
        return True
    try:
        model._meta.get_field(AUTHOR_FIELD)
    except FieldDoesNotExist:
        return False
    return True


def _mark_stamping(wrapper):
    setattr(wrapper, _STAMPING_MARKER, True)
    return wrapper


# Stamping is idempotent: a wrapped body that calls super() into another wrapped
# method stamps the same author twice.
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
        return create(self, self._stamp_author_for_create(validated_data))

    return _mark_stamping(stamped_create)


def _wrap_update(update):
    @functools.wraps(update)
    def stamped_update(self, instance, validated_data):
        return update(self, instance, self._stamp_author_for_update(instance, validated_data))

    return _mark_stamping(stamped_update)
