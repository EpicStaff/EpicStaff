from rbac.access.resolver import PermissionResolver
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.fields import resolve_active_org_id
from rest_framework import serializers
from tables.services.secrets.secret_resolver import secret_names_in_headers
from utils.logger import logger

_DENIED = (
    'Changing the secrets referenced here requires the "Use" permission on '
    "Secrets. The existing selection was left unchanged. Ask an organization "
    "admin to grant it."
)

_DESTINATION_DENIED = (
    'Changing where this sends its secrets requires the "Use" permission on '
    "Secrets. The existing value was left unchanged. Ask an organization admin "
    "to grant it."
)

_IMPORT_DENIED = (
    'Importing secret references requires the "Use" permission on Secrets. '
    "Nothing was imported. Ask an organization admin to grant it."
)


class SecretReferenceGuard:
    """Rejects a payload that changes which secret reaches where without secrets:USE.

    Three kinds of change are gated, each by the same delta rule (omitted or resent
    unchanged needs nothing): a secret FK/M2M field, the set of secret names that
    `epicstaff_secret(<name>)` markers in a header field reference, and the
    destination a secret-bearing row sends its request to.
    """

    def __init__(self, resolver=None):
        self._resolver = resolver or PermissionResolver()

    def assert_unchanged_or_permitted(self, *, serializer, attrs, fields) -> None:
        """Raise ValidationError for each guarded field whose value changes without USE."""
        for field_name in fields:
            source = self._writable_source(serializer=serializer, field_name=field_name)
            if source is None or source not in attrs:
                continue
            incoming = self._normalize(value=attrs[source])
            current = self.current_ids(serializer=serializer, source=source)
            if incoming == current:
                continue
            self._assert_may_use(serializer=serializer, field_name=field_name)

    def assert_header_markers_unchanged_or_permitted(self, *, serializer, attrs, fields) -> None:
        """Raise ValidationError when a header field's set of marker names changes without USE.

        Only the names count: editing a header's other text, adding a header with no
        marker, or reordering keys reaches no new secret. On create the persisted set
        is empty, so any marker at all needs USE.
        """
        for field_name in fields:
            source = self._writable_source(serializer=serializer, field_name=field_name)
            if source is None or source not in attrs:
                continue
            incoming = secret_names_in_headers(attrs[source])
            current = secret_names_in_headers(
                self._current_value(serializer=serializer, source=source)
            )
            if incoming == current:
                continue
            self._assert_may_use(serializer=serializer, field_name=field_name)

    def assert_destination_unchanged_or_permitted(self, *, serializer, attrs) -> None:
        """Raise ValidationError when a secret-bearing row's destination changes without USE.

        The serializer describes its destination through `get_secret_destination(attrs)`
        and whether a secret travels there through `carries_secret_reference(attrs)`
        (see SecretReferenceGuardMixin). Create is never gated here: a new row reaches
        a secret only through a reference, which the two checks above already gate.
        """
        if serializer.instance is None:
            return
        incoming = serializer.get_secret_destination(attrs)
        current = serializer.get_secret_destination({})
        changed = [name for name, value in incoming.items() if current.get(name) != value]
        if not changed:
            return
        if not serializer.carries_secret_reference(attrs):
            return
        self._assert_may_use(
            serializer=serializer, field_name=changed[0], message=_DESTINATION_DENIED
        )

    def assert_imported_header_markers_permitted(
        self, *, user, org_id, headers, field_name
    ) -> None:
        """Raise ValidationError when an imported row's headers carry markers and `user` lacks USE.

        An imported row is always new, so the persisted set is empty and any marker is
        a change. The markers resolve by name in the importing org, which is why a file
        written elsewhere must not attach that org's secrets for a caller without USE.
        """
        if not secret_names_in_headers(headers):
            return
        if user is None or not self._may_use(user=user, org_id=org_id):
            raise serializers.ValidationError({field_name: _IMPORT_DENIED})

    def current_ids(self, *, serializer, source) -> frozenset:
        """The pks the persisted row links to through `source`, binned rows included.

        A row in the recycle bin keeps the links to it until it's purged, so "what this
        row links to now" must count it: the guard compares against it, and
        KeptLinkPrimaryKeyRelatedField accepts it unchanged.
        """
        return self._normalize(value=self._current_value(serializer=serializer, source=source))

    @staticmethod
    def _writable_source(*, serializer, field_name) -> str | None:
        """The attrs key a writable guarded field fills, or None when the field is absent or read-only."""
        field = serializer.fields.get(field_name)
        if field is None or field.read_only:
            return None
        return field.source

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

    def _assert_may_use(self, *, serializer, field_name, message=_DENIED) -> None:
        """Raise unless the caller holds secrets:USE in the active org."""
        request = serializer.context.get("request")
        if request is None:
            logger.warning(
                "SecretReferenceGuard denied '{}' on {}: no request in serializer "
                "context, so the active org cannot be resolved.",
                field_name,
                type(serializer).__name__,
            )
            raise serializers.ValidationError({field_name: message})
        if not self._may_use(user=request.user, org_id=resolve_active_org_id(request)):
            raise serializers.ValidationError({field_name: message})

    def _may_use(self, *, user, org_id) -> bool:
        effective = self._resolver.resolve(user=user, org_id=org_id)
        return effective.can(ResourceType.SECRETS.value, Permission.USE)


secret_reference_guard = SecretReferenceGuard()
