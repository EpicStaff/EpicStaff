from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from rbac.access.resolver import PermissionResolver
from rbac.authorship import resolve_author
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.fields import resolve_active_org_id
from rest_framework import serializers
from tables.services.secrets.exceptions import SecretUseDeniedError
from tables.services.secrets.secret_resolver import extract_secret_marker_names
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


@dataclass(frozen=True)
class SecretActor:
    """Who is writing, and the organization whose secrets:USE grant decides for them."""

    user: object
    org_id: int | None


@dataclass(frozen=True)
class SecretReferenceChange:
    """A write to a field that decides which secrets a row reaches.

    For a secret FK/M2M field the sets hold linked secret pks; for a header field they
    hold the secret names its `epicstaff_secret(<name>)` markers reference.
    """

    denied_message: ClassVar[str] = _DENIED

    field_name: str
    incoming: frozenset
    current: frozenset

    def changed_field_name(self) -> str | None:
        return None if self.incoming == self.current else self.field_name


@dataclass(frozen=True)
class SecretDestinationChange:
    """A write to where a secret-bearing row sends its request, each side as {field name: value}."""

    denied_message: ClassVar[str] = _DESTINATION_DENIED

    incoming: Mapping[str, object]
    current: Mapping[str, object]

    def changed_field_name(self) -> str | None:
        return next(
            (name for name, value in self.incoming.items() if self.current.get(name) != value),
            None,
        )


SecretChange = SecretReferenceChange | SecretDestinationChange


class SecretReferenceGuard:
    """Rejects a write that changes which secret reaches where without secrets:USE.

    Every writer -- the API's serializers, import, and any future one -- describes its
    write as a list of changes (a SecretPolicy builds them) and calls
    `assert_permitted`. The delta rule is the same for each kind: a change whose
    incoming side equals its current side (omitted, or resent unchanged) needs nothing.
    """

    def __init__(self, resolver=None):
        self._resolver = resolver or PermissionResolver()

    def assert_no_new_markers_or_permitted(self, *, serializer, attrs, fields) -> None:
        """Raise ValidationError when a guarded header field gains a secret marker without USE.

        A `epicstaff_secret(<name>)` marker makes a run send that secret's plaintext,
        so adding one is a secret reference like `api_key_secret_id`. Markers the
        persisted value already has, or removing markers, need no permission, so a
        caller without USE can still edit the rest of the resource.
        """
        for field_name in fields:
            field = serializer.fields.get(field_name)
            if field is None or field.read_only:
                continue
            source = field.source
            if source not in attrs:
                continue
            incoming = extract_secret_marker_names(attrs[source])
            current = extract_secret_marker_names(
                self._current_value(serializer=serializer, source=source)
            )
            if incoming - current:
                self._assert_may_use(serializer=serializer, field_name=field_name)

    def assert_may_use(self, *, user, org_id: int | None, field_name: str) -> None:
        """Raise ValidationError unless `user` holds secrets:USE in `org_id`.

        For paths with no request to read the active org from, such as import.
        """
        if user is None:
            raise serializers.ValidationError({field_name: _DENIED})
        effective = self._resolver.resolve(user=user, org_id=org_id)
        if not effective.can(ResourceType.SECRETS.value, Permission.USE):
            raise serializers.ValidationError({field_name: _DENIED})

    def requires_use(self, changes: Sequence[SecretChange]) -> bool:
        """Whether any change actually changes something, so the actor must hold USE.

        Lets a writer skip resolving its actor when nothing changed: resolving the
        active org costs a query and fails outright on a request without one.
        """
        return self._first_changed(changes) is not None

    def assert_permitted(
        self, *, actor: SecretActor | None, changes: Sequence[SecretChange]
    ) -> None:
        """Raise SecretUseDeniedError for the first change unless `actor` holds secrets:USE.

        A missing actor is denied: a writer that cannot say who is writing must not
        attach secrets.

        Raises:
            SecretUseDeniedError: Something changed and `actor` is missing or lacks USE.
        """
        first_changed = self._first_changed(changes)
        if first_changed is None:
            return
        change, field_name = first_changed
        if actor is None:
            logger.warning(
                "SecretReferenceGuard denied '{}': no actor, so the active org cannot be resolved.",
                field_name,
            )
            raise SecretUseDeniedError(field_name=field_name, message=change.denied_message)
        if not self._holds_use(actor):
            raise SecretUseDeniedError(field_name=field_name, message=change.denied_message)

    def authorize_write(
        self, *, policy, write, resolve_actor: Callable[[], SecretActor | None]
    ) -> dict:
        """Gate one row's write under `policy` and return the approval attrs it earns.

        Who approves a row's secret binding, and when, is decided here for every writer:

        - A change that needs USE (a reference, a header marker, a secret-bearing
          destination -- including creating a row that carries a secret) must be
          permitted, and its actor becomes the approver.
        - Otherwise, a USE-holding person saving a row whose secret goes somewhere custom
          re-approves it: that is how an admin restores delivery by re-saving.
        - Any other save leaves the approver alone (empty attrs).

        `resolve_actor` is called at most once and only when an actor is needed:
        resolving the active org costs a query and fails on a request without one.

        Raises:
            SecretUseDeniedError: A change needs USE the actor does not hold.
        """
        changes = policy.changes(write)
        if self.requires_use(changes):
            actor = resolve_actor()
            self.assert_permitted(actor=actor, changes=changes)
            return policy.binding_approval(actor)
        # A new row reaches a secret only through a gated change, handled above.
        if (
            write.instance is not None
            and policy.records_binding_approval
            and policy.sends_secret_to_custom_destination(write)
        ):
            return self.approval_by_use_holder(policy=policy, actor=resolve_actor())
        return {}

    def approval_by_use_holder(self, *, policy, actor: SecretActor | None) -> dict:
        """The approval attrs naming `actor`, but only for a person who holds USE; else none.

        Never stamps NULL: a save by the system API-key principal, or by someone without
        USE, must not erase a valid approver. Used for re-approval and by writers that
        create secret-bearing rows without a gated change (quickstart).
        """
        if not policy.records_binding_approval or actor is None:
            return {}
        if resolve_author(actor.user) is None or not self.may_use(actor):
            return {}
        return policy.binding_approval(actor)

    def may_use(self, actor: SecretActor | None) -> bool:
        """Whether `actor` holds secrets:USE in its org; a missing actor or a non-member does not."""
        if actor is None:
            return False
        try:
            return self._holds_use(actor)
        except OrgMembershipRequiredError:
            return False

    def _holds_use(self, actor: SecretActor) -> bool:
        effective = self._resolver.resolve(user=actor.user, org_id=actor.org_id)
        return effective.can(ResourceType.SECRETS.value, Permission.USE)

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
        self.assert_may_use(
            user=request.user, org_id=resolve_active_org_id(request), field_name=field_name
        )

    @staticmethod
    def _first_changed(changes) -> tuple[SecretChange, str] | None:
        for change in changes:
            field_name = change.changed_field_name()
            if field_name is not None:
                return change, field_name
        return None


secret_reference_guard = SecretReferenceGuard()
