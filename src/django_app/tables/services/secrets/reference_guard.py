from django.db.models import ForeignKey
from rbac.access.principals import is_pinned_org_principal, is_plugin_credential
from rbac.access.resolver import PermissionResolver
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.fields import resolve_active_org_id
from rest_framework import exceptions, serializers
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
_ENDPOINT_NOT_SETTABLE = (
    "This credential cannot set where a model sends requests; the organization's "
    "configurations may use this model with their own keys."
)
_INCOMPLETE_PRINCIPAL = "This credential cannot write here."
_MAY_USE_SECRETS_ATTRIBUTE = "_secret_reference_guard_may_use"


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

        The persisted value is read only when it decides something: for a field the
        payload carries, when the caller lacks secrets:USE (resending it unchanged is
        allowed); for a field it leaves out, when the caller is a pinned-org principal.
        secrets:USE is resolved once per request, so a bulk save of many rows asks once.
        """
        principal = _pinned_principal(serializer=serializer)
        for field_name in fields:
            field = serializer.fields.get(field_name)
            if field is None or field.read_only:
                continue
            source = field.source
            if source in attrs:
                referenced = self._normalize(value=attrs[source])
                if not self._caller_may_use(
                    serializer=serializer
                ) and referenced != self.current_ids(serializer=serializer, source=source):
                    self._refuse_change(serializer=serializer, field_name=field_name)
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
            return _stored_value(current, source)
        return _stored_value(serializer.instance, source)

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

    def _caller_may_use(self, *, serializer) -> bool:
        """Whether the caller holds secrets:USE in the active org; False without a request.

        Kept on the request: rights do not change within it, and a bulk save validates
        many rows with one request.
        """
        request = serializer.context.get("request")
        if request is None:
            return False
        may_use = getattr(request, _MAY_USE_SECRETS_ATTRIBUTE, None)
        if may_use is None:
            effective = self._resolver.resolve(
                user=request.user, org_id=resolve_active_org_id(request)
            )
            may_use = effective.can(ResourceType.SECRETS.value, Permission.USE)
            setattr(request, _MAY_USE_SECRETS_ATTRIBUTE, may_use)
        return may_use

    @staticmethod
    def _refuse_change(*, serializer, field_name) -> None:
        if serializer.context.get("request") is None:
            logger.warning(
                "SecretReferenceGuard denied '{}' on {}: no request in serializer "
                "context, so the active org cannot be resolved.",
                field_name,
                type(serializer).__name__,
            )
        raise serializers.ValidationError({field_name: _DENIED})


class SecretDestinationGuard:
    """Keeps a pinned-org principal from deciding where any model sends requests.

    A config sends its key to the endpoint of the model it points at (an LLM model's
    `base_url`, an Azure `deployment_id`), and a person's config may come to use any model
    of the organization: quickstart reuses one by name, and a person can pick one. So a
    pinned-org principal never sets or changes a model's endpoint fields, on its own rows
    or the organization's, on create or on update. The model's name and provider only
    choose between vendor hosts and stay editable. People are not limited.
    """

    def assert_may_change_endpoints(self, *, serializer, attrs, fields) -> None:
        """Raise ValidationError when a pinned-org principal sets or changes an endpoint field.

        Args:
            fields: Sources of the fields that decide where the model sends requests.
        """
        self.assert_endpoints_untouched(
            principal=_pinned_principal(serializer=serializer),
            instance=serializer.instance,
            values=attrs,
            fields=fields,
        )

    def assert_endpoints_untouched(self, *, principal, instance, values, fields) -> None:
        """Raise ValidationError for each of `fields` the write would leave different from the row.

        Nothing happens for a person (`principal` None). A field the write leaves out, or
        sends unchanged, never counts; on a new row (`instance` None) any non-empty value
        does.
        """
        if principal is None:
            return
        changed = [
            source
            for source in fields
            if source in values
            and _endpoint_value(values[source]) != _endpoint_value(getattr(instance, source, None))
        ]
        if changed:
            raise serializers.ValidationError(dict.fromkeys(changed, _ENDPOINT_NOT_SETTABLE))


def pinned_principal_of_user(user):
    """Return `user` when it is a pinned-org principal, None for anyone else.

    Fails closed: a caller that carries the plugin-credential flag but does not implement
    `PinnedOrgPrincipal` is refused, never taken for a person whose writes nothing limits.

    Raises:
        PermissionDenied: The caller is a plugin credential without the protocol.
    """
    if is_pinned_org_principal(user):
        return user
    if getattr(user, "is_plugin_credential", False) is True:
        _refuse_incomplete_principal(user)
    return None


def _pinned_principal(*, serializer):
    """The request's pinned-org principal, or None for a person and without a request.

    Raises:
        PermissionDenied: The request authenticated with a plugin credential whose user
            does not implement `PinnedOrgPrincipal`.
    """
    request = serializer.context.get("request")
    if request is None:
        return None
    user = getattr(request, "user", None)
    principal = pinned_principal_of_user(user)
    if principal is None and is_plugin_credential(request):
        _refuse_incomplete_principal(user)
    return principal


def _refuse_incomplete_principal(user) -> None:
    logger.error(
        "A plugin credential's user ({}) does not implement PinnedOrgPrincipal; its write "
        "was refused",
        type(user).__name__,
    )
    raise exceptions.PermissionDenied(_INCOMPLETE_PRINCIPAL)


def _stored_value(row, source):
    """`row`'s persisted value for `source`; for a foreign key, its id column.

    Reading the id never loads the related row, so a write that leaves the field out
    costs no query for it.
    """
    if row is None:
        return None
    meta = getattr(row, "_meta", None)
    field = (
        next((field for field in meta.concrete_fields if field.name == source), None)
        if meta is not None
        else None
    )
    if isinstance(field, ForeignKey):
        return getattr(row, field.attname)
    return getattr(row, source, None)


def _endpoint_value(value):
    # An empty value and no value both mean the provider's default endpoint.
    return value or None


secret_reference_guard = SecretReferenceGuard()
secret_destination_guard = SecretDestinationGuard()
