from rest_framework import serializers
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
    """A required, non-empty list of at most BULK_DELETE_MAX_IDS positive integer ids.

    Any invalid item yields one message for the whole list instead of one error per
    index: the client marks the field, not a position in it.
    """

    default_error_messages = {
        "null": "Must be a list of positive integers.",
        "not_a_list": "Must be a list of positive integers.",
        "invalid_item": "Must be a list of positive integers.",
        "empty": "Must not be empty.",
        "max_length": "Must have at most {max_length} items.",
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
