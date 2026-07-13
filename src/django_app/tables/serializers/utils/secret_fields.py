from rest_framework import serializers
from rest_framework.fields import SkipField


class SecretCharField(serializers.CharField):
    """
    Write-through field for secrets (API keys, tokens).

    Read: returns a mask instead of a value.
    Write: if a mask is received (the client returned it as is), the field is skipped.
    (SkipField), so on update, the old secret is preserved in the database.
    On create, the field is missing and the model default (null) is used.

    """

    def __init__(self, *args, visible_tail: int = 4, **kwargs):
        self.visible_tail = visible_tail
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("trim_whitespace", False)
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        if value is None or value == "":
            return value
        s = value if isinstance(value, str) else str(value)
        n = len(s)
        if n <= 8:
            return "********"
        return "*" * (n - 4) + s[-self.visible_tail :]

    def to_internal_value(self, data):
        if isinstance(data, str) and data.startswith("*****"):
            raise SkipField()
        return super().to_internal_value(data)
