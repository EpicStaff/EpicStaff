from rest_framework import serializers


class BoundedListField(serializers.ListField):
    """ListField that rejects an oversized list before validating its items.

    DRF checks `max_length` only after validating every item, so an oversized
    list of junk costs one validation and one error per item.
    """

    def to_internal_value(self, data):
        if self.max_length is not None and isinstance(data, list) and len(data) > self.max_length:
            self.fail("max_length", max_length=self.max_length)
        return super().to_internal_value(data)
