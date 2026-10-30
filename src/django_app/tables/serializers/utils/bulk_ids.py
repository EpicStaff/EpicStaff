from rest_framework import serializers
from rest_framework.settings import api_settings
from tables.serializers.utils.list_fields import BoundedListField

# Largest number of ids one bulk request may carry. The shared frontend bulk delete
# refuses larger selections (BULK_DELETE_MAX_IDS in bulk-delete.model.ts); the session
# lists send one page's selection at a time.
BULK_DELETE_MAX_IDS = 500


class StrictPositiveIntegerField(serializers.IntegerField):
    """IntegerField that takes only a JSON integer of at least 1.

    DRF's IntegerField coerces `"5"` and `5.0` to 5; this field refuses
    anything that is not already an int. `bool` is an `int` subclass, so it is
    refused explicitly to make the intent clear: DRF's own `int("True")` would
    reject it too, but `true` must never reach the ORM as id 1.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("min_value", 1)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, int):
            self.fail("invalid")
        return super().to_internal_value(data)


class BulkIdListField(BoundedListField):
    """A non-empty id list whose messages are fragments, for BulkIdListSerializer only.

    Required, non-empty, at most BULK_DELETE_MAX_IDS positive integer ids. Every
    error message is a predicate (`"must not be empty."`) that
    BulkIdListSerializer.error_message prefixes with the field name, so the
    field reads wrongly in a plain DRF error response. Any invalid item yields
    one message instead of one error per index.
    """

    default_error_messages = {
        "required": "is required.",
        "null": "must be a list of positive integers.",
        "not_a_list": "must be a list of positive integers.",
        "invalid_item": "must be a list of positive integers.",
        "empty": "must not be empty.",
        "max_length": "must have at most {max_length} items.",
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("child", StrictPositiveIntegerField())
        kwargs.setdefault("allow_empty", False)
        kwargs.setdefault("max_length", BULK_DELETE_MAX_IDS)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError as error:
            # ListField reports item errors as a dict keyed by index.
            if isinstance(error.detail, dict):
                self.fail("invalid_item")
            raise


class BulkIdListSerializer(serializers.Serializer):
    """Base for a request body that holds one BulkIdListField.

    Bulk endpoints that predate the shared bulk-delete action answer a bad body
    with a single sentence under their own key (`detail` or `error`), so the
    serializer exposes its first error as that sentence.
    """

    @property
    def error_message(self) -> str:
        """Return the first validation error as a sentence; call after is_valid() fails."""
        field_name, messages = next(iter(self.errors.items()))
        if field_name == api_settings.NON_FIELD_ERRORS_KEY:
            return str(messages[0])
        return f"{field_name} {messages[0]}"
