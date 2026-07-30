from rest_framework import serializers
from rest_framework.fields import SkipField

from tables.services.secrets import secret_service


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


class MaskedSecretField(serializers.CharField):
    """
    Write-through field for a `Secret` FK (API keys, tokens).

    Read: FK is None -> None. FK set -> a fixed mask plus the real tail
    (e.g. "****abcd"), never the plaintext or its true length.
    Write: a value starting with the mask prefix is treated as "unchanged"
    (SkipField) -- round-tripping a GET response back on a PUT preserves the
    existing secret. None/"" detaches the FK (does not delete the Secret
    row). Any other string is passed through as plaintext for
    SecretFieldWriteMixin to turn into a Secret.
    """

    _MASK_PREFIX = "****"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("allow_blank", True)
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        if value is None:
            return None
        return f"{self._MASK_PREFIX}{value.tail}"

    def to_internal_value(self, data):
        if isinstance(data, str) and data.startswith(self._MASK_PREFIX):
            raise SkipField()
        if data in (None, ""):
            return None
        return super().to_internal_value(data)


class SecretFieldWriteMixin:
    """Create/rotate the Secret(s) behind this serializer's MaskedSecretField(s)."""

    secret_fk_fields: list = []

    def create(self, validated_data):
        pending = {
            f: validated_data.pop(f)
            for f in self.secret_fk_fields
            if f in validated_data
        }
        instance = super().create(validated_data)
        self._write_secrets(instance, pending)
        return instance

    def update(self, instance, validated_data):
        pending = {
            f: validated_data.pop(f)
            for f in self.secret_fk_fields
            if f in validated_data
        }
        instance = super().update(instance, validated_data)
        self._write_secrets(instance, pending)
        return instance

    def _resolve_org(self, instance):
        return instance.org

    def _write_secrets(self, instance, pending):
        if not pending:
            return
        org = self._resolve_org(instance)
        changed = False
        for attr, text in pending.items():
            existing = getattr(instance, attr)
            if text in (None, ""):
                setattr(instance, attr, None)
            elif existing is not None:
                secret_service.update(existing, text=text)
                continue
            else:
                secret = secret_service.create_for_field(
                    text=text, org=org, instance=instance, field_name=attr
                )
                setattr(instance, attr, secret)
            changed = True
        if changed:
            instance.save()
