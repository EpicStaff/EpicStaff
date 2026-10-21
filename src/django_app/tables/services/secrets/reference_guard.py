from rbac.access.principals import is_pinned_org_principal
from rbac.access.resolver import PermissionResolver
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.fields import resolve_active_org_id
from rest_framework import serializers
from utils.logger import logger

_DENIED = (
    'Changing the secrets referenced here requires the "Use" permission on '
    "Secrets. The existing selection was left unchanged. Ask an organization "
    "admin to grant it."
)
# Name no secret: the caller may not even know which one the row references.
_NOT_REFERENCEABLE = (
    "This credential can reference only secrets it created, so it cannot save a row "
    "that references any other secret."
)
_NOT_REPOINTABLE = (
    "This credential can change where requests are sent only on models it created: "
    "configurations of the organization use this one with their own keys."
)


class SecretReferenceGuard:
    """Gates the secrets a written row references.

    Changing a reference needs secrets:USE. A pinned-org principal (a plugin's service
    account) may also write only rows whose references, changed or not, it is allowed to
    make (`PinnedOrgPrincipal.may_reference_secrets`): otherwise it could point a row it
    controls (an LLM config's `base_url`, a Python node's code) at a secret of the
    organization and receive its value.
    """

    def __init__(self, resolver=None):
        self._resolver = resolver or PermissionResolver()

    def assert_unchanged_or_permitted(self, *, serializer, attrs, fields) -> None:
        """Raise ValidationError for each guarded field the caller may not write as it ends up.

        A field whose value changes needs secrets:USE. For a pinned-org principal, every
        guarded field is checked on every create and update, whether the payload carries
        it or not: the incoming value when it does, the persisted one when it does not.
        """
        principal = _pinned_principal(serializer=serializer)
        for field_name in fields:
            field = serializer.fields.get(field_name)
            if field is None or field.read_only:
                continue
            source = field.source
            if source in attrs:
                referenced = self._normalize(value=attrs[source])
                if referenced != self.current_ids(serializer=serializer, source=source):
                    self._assert_may_use(serializer=serializer, field_name=field_name)
            elif principal is not None:
                referenced = self.current_ids(serializer=serializer, source=source)
            else:
                continue
            if principal is not None and not principal.may_reference_secrets(referenced):
                raise serializers.ValidationError({field_name: _NOT_REFERENCEABLE})

    def current_ids(self, *, serializer, source) -> frozenset:
        """The pks the persisted row links to through `source`, binned rows included.

        A row in the recycle bin keeps the links to it until it's purged, so "what this
        row links to now" must count it: the guard compares against it, and
        KeptLinkPrimaryKeyRelatedField accepts it unchanged.
        """
        return self._normalize(value=self._current_value(serializer=serializer, source=source))

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
        """Collapse None, a single row (a Secret or a WebhookTrigger), and a related manager to one comparable set."""
        if value is None:
            return frozenset()
        if hasattr(value, "all"):
            # A related manager reads the live manager; a link to a binned row still counts.
            rows = value(manager="all_objects") if callable(value) else value
            return frozenset(row.pk for row in rows.all())
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
        effective = self._resolver.resolve(user=request.user, org_id=resolve_active_org_id(request))
        if not effective.can(ResourceType.SECRETS.value, Permission.USE):
            raise serializers.ValidationError({field_name: _DENIED})


class SecretDestinationGuard:
    """Keeps a pinned-org principal from moving where an organization's secrets are sent.

    A config that holds a secret sends it to the endpoint of the model it points at (an
    LLM model's `base_url` and provider). The config itself is covered by
    `SecretReferenceGuard`, but the model row is not: it references no secret. A pinned-org
    principal may change those endpoint fields only on a row it owns
    (`PinnedOrgPrincipal.owns`), which a row it created always is. People are not limited.
    """

    def assert_may_change_endpoints(self, *, serializer, attrs, fields) -> None:
        """Raise ValidationError when a pinned-org principal changes an endpoint field of a row it does not own.

        Args:
            fields: Sources of the fields that decide where requests carrying a config's
                key go. A field the payload leaves out, or sends unchanged, never counts.
        """
        instance = serializer.instance
        principal = _pinned_principal(serializer=serializer)
        if instance is None or principal is None:
            return
        changed = [
            source
            for source in fields
            if source in attrs
            and _endpoint_value(attrs[source]) != _endpoint_value(getattr(instance, source))
        ]
        if changed and not principal.owns(instance):
            raise serializers.ValidationError(dict.fromkeys(changed, _NOT_REPOINTABLE))


def _endpoint_value(value):
    # An empty URL and no URL both mean the provider's default endpoint; a row compares by pk.
    return getattr(value, "pk", value) or None


def _pinned_principal(*, serializer):
    """The request's pinned-org principal, or None for a person and without a request."""
    request = serializer.context.get("request")
    user = getattr(request, "user", None)
    return user if is_pinned_org_principal(user) else None


secret_reference_guard = SecretReferenceGuard()
secret_destination_guard = SecretDestinationGuard()
