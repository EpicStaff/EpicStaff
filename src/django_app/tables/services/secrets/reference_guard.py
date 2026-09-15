from rest_framework import serializers

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.org_scoped_fields import resolve_active_org_id
from tables.services.rbac.permission_resolver import PermissionResolver
from utils.logger import logger

_DENIED = (
    'Changing the secrets referenced here requires the "Use" permission on '
    "Secrets. The existing selection was left unchanged. Ask an organization "
    "admin to grant it."
)


class SecretReferenceGuard:
    """Rejects a payload that changes a secret reference without secrets:USE."""

    def __init__(self, resolver=None):
        self._resolver = resolver or PermissionResolver()

    def assert_unchanged_or_permitted(self, *, serializer, attrs, fields) -> None:
        """Raise ValidationError for each guarded field whose value changes without USE."""
        for field_name in fields:
            field = serializer.fields.get(field_name)
            if field is None or field.read_only:
                continue
            source = field.source
            if source not in attrs:
                continue
            incoming = self._normalize(value=attrs[source])
            current = self._normalize(
                value=self._current_value(serializer=serializer, source=source)
            )
            if incoming == current:
                continue
            self._assert_may_use(serializer=serializer, field_name=field_name)

    @staticmethod
    def _current_value(*, serializer, source):
        """The persisted value, via the serializer's hook, its declared parent attribute, or its own instance, in that order."""
        hook = getattr(serializer, "get_current_secret_reference", None)
        if hook is not None:
            return hook(source)
        parent_attribute = getattr(serializer, "parent_attribute", None)
        if parent_attribute is not None:
            parent_instance = getattr(serializer.parent, "instance", None)
            current = (
                getattr(parent_instance, parent_attribute, None)
                if parent_instance is not None
                else None
            )
            return getattr(current, source, None) if current is not None else None
        return getattr(serializer.instance, source, None)

    @staticmethod
    def _normalize(*, value) -> frozenset:
        """Collapse None, a single Secret, and a related manager to one comparable set."""
        if value is None:
            return frozenset()
        if hasattr(value, "all"):
            return frozenset(secret.pk for secret in value.all())
        if isinstance(value, (list, tuple, set, frozenset)):
            return frozenset(getattr(item, "pk", item) for item in value)
        return frozenset({getattr(value, "pk", value)})

    def _assert_may_use(self, *, serializer, field_name) -> None:
        """Raise unless the caller holds secrets:USE in the active org."""
        request = serializer.context.get("request")
        if request is None:
            logger.warning(
                "SecretReferenceGuard denied '{}' on {}: no request in serializer "
                "context, so the active org cannot be resolved.",
                field_name,
                type(serializer).__name__,
            )
            raise serializers.ValidationError({field_name: _DENIED})
        effective = self._resolver.resolve(
            user=request.user, org_id=resolve_active_org_id(request)
        )
        if not effective.can(ResourceType.SECRETS.value, Permission.USE):
            raise serializers.ValidationError({field_name: _DENIED})


secret_reference_guard = SecretReferenceGuard()
