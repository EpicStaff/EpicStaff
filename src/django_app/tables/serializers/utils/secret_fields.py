from rest_framework import serializers
from rest_framework.fields import SkipField


MASK_MARKER = "****"
PLACEHOLDER = "********"


class SecretCharField(serializers.CharField):
    """
    Write-through field for secrets (API keys, tokens).

    Read: returns a mask instead of a value.
    Write: if a mask is received (the client returned it as is), the field is skipped.
    (SkipField), so on update, the old secret is preserved in the database.
    On create, the field is missing and the model default (null) is used.

    mask_style="tail" -> "****" + last `visible_tail` characters
    mask_style="placeholder" -> always "********"
    A short secret (len <= visible_tail) in the tail style is also returned as "********".
    """

    def __init__(
        self, *args, mask_style: str = "placeholder", visible_tail: int = 7, **kwargs
    ):
        self.mask_style = mask_style
        self.visible_tail = visible_tail
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("trim_whitespace", False)
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        if value in (None, ""):
            return value
        s = str(value)
        if self.mask_style == "tail" and len(s) > self.visible_tail:
            return f"{MASK_MARKER}{s[-self.visible_tail :]}"
        return PLACEHOLDER

    def to_internal_value(self, data):
        if isinstance(data, str) and data.startswith(MASK_MARKER):
            raise SkipField()
        return super().to_internal_value(data)
