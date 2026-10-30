from dataclasses import dataclass, field

from rbac.access.resolver import PermissionResolver
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models.enums import Permission, ResourceType
from tables.services.secrets.exceptions import SecretUseDeniedError
from tables.services.secrets.linked_ids import linked_ids
from tables.services.secrets.pinned_principal_rules import (
    NOT_REFERENCEABLE,
    may_reference_marker_names,
    pinned_principal_of_user,
)
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

_CODE_DENIED = (
    'Changing code that reads secrets, or what it runs with, requires the "Use" '
    "permission on Secrets. The existing value was left unchanged. Ask an organization "
    "admin to grant it."
)


@dataclass(frozen=True)
class SecretActor:
    """Who is writing, and in which organization their secrets:USE is looked up."""

    user: object
    org_id: int | None
    # Holds whether the actor has secrets:USE once it is resolved; None resolves it on
    # every check. `actor_from_request` gives each request one actor with a memo, as
    # rights do not change within a request, so a bulk save of many rows resolves once.
    use_memo: list[bool] | None = field(default=None, compare=False, repr=False)

    @classmethod
    def for_user(cls, user, org_id: int | None) -> "SecretActor | None":
        """Return the actor for `user` writing in `org_id`, or None when there is no user.

        For writes made outside a request's own serializer checks (a copy, a version
        restore). Memoizes secrets:USE, so the write resolves it once however many
        rows it checks.
        """
        return cls(user=user, org_id=org_id, use_memo=[]) if user is not None else None

    @property
    def principal(self):
        """The pinned-org principal (a plugin's service account) writing, or None for a person.

        Raises:
            IncompletePluginCredentialError: The user carries the plugin-credential flag without
                implementing `PinnedOrgPrincipal`.
        """
        return pinned_principal_of_user(self.user)


def principal_of(actor: SecretActor | None):
    """The pinned-org principal writing, or None for a person or no actor."""
    return actor.principal if actor is not None else None


class SecretUseService:
    """Decides whether a write needs secrets:USE, and denies it when the actor lacks it.

    Every check compares the persisted value with the value after the write, so a
    resend of what is already stored needs no permission. A pinned-org principal is
    held to more: every secret the row references after the write, changed or not,
    must be one it may reference (`pinned_principal_rules`). Knows nothing about
    requests or serializers: callers pass plain values and let SecretUseDeniedError
    propagate to the exception handler, or render it in their own shape (bulk save).
    """

    def __init__(self, resolver=None):
        self._resolver = resolver or PermissionResolver()

    def may_use(self, actor: SecretActor | None) -> bool:
        """Return whether `actor` holds secrets:USE in its organization; no actor or no membership is False."""
        if actor is None:
            return False
        if actor.use_memo is None:
            return self._resolve_use(actor)
        if not actor.use_memo:
            actor.use_memo.append(self._resolve_use(actor))
        return actor.use_memo[0]

    def check_references(
        self, actor: SecretActor | None, *, field_path: tuple[str, ...], current, incoming
    ) -> None:
        """Require USE when the set of linked secrets changes, including set to empty.

        Args:
            current: What the row links to now: None, a row, a pk, a related manager
                (binned rows count) or an iterable of rows or pks.
            incoming: What it will link to after the write, in any of the same forms.

        Raises:
            SecretUseDeniedError: The set changes and `actor` lacks secrets:USE, or
                `actor` is a pinned-org principal and may not reference every secret
                of `incoming`.
        """
        incoming_ids = linked_ids(incoming)
        if linked_ids(current) != incoming_ids:
            self._require_use(actor, field_path=field_path, message=_DENIED)
        principal = principal_of(actor)
        if principal is not None and not principal.may_reference_secrets(incoming_ids):
            raise SecretUseDeniedError(field_path=field_path, message=NOT_REFERENCEABLE)

    def check_markers(
        self,
        actor: SecretActor | None,
        *,
        field_path: tuple[str, ...],
        current_headers,
        incoming_headers,
    ) -> None:
        """Require USE when a header dict gains an `epicstaff_secret(<name>)` marker.

        A marker makes a run send that secret's plaintext, so adding one is a secret
        reference. Keeping or removing markers is free, so a caller without USE can
        still edit the rest of the resource.

        A pinned-org principal is also checked on every write, whatever it changes:
        every marker of `incoming_headers` must name a secret it may reference
        (`may_reference_marker_names`).

        Raises:
            SecretUseDeniedError: A new marker name appears and `actor` lacks secrets:USE,
                or `actor` is a pinned-org principal and a marker names a secret it may
                not reference.
        """
        incoming_names = extract_secret_marker_names(incoming_headers)
        if incoming_names - extract_secret_marker_names(current_headers):
            self._require_use(actor, field_path=field_path, message=_DENIED)
        principal = principal_of(actor)
        if principal is not None and not may_reference_marker_names(
            principal=principal, names=incoming_names
        ):
            raise SecretUseDeniedError(field_path=field_path, message=NOT_REFERENCEABLE)

    def check_destination(
        self,
        actor: SecretActor | None,
        *,
        field_path: tuple[str, ...],
        carries_secret: bool,
        current,
        incoming,
    ) -> None:
        """Require USE when a secret-bearing row changes where it sends requests.

        Pointing a row that carries a secret at a host the caller picks sends that
        secret there, which is a use of it. A row that carries no secret may change
        its destination freely.

        Args:
            carries_secret: Whether the row, after the write, carries a secret.
            current: The destination now: a value, or a tuple of values when the
                destination is made of several fields. None and "" are the same.
            incoming: The destination after the write, in the same form.

        Raises:
            SecretUseDeniedError: The destination changes, the row carries a secret
                and `actor` lacks secrets:USE.
        """
        if not carries_secret:
            return
        if _normalize_destination(current) == _normalize_destination(incoming):
            return
        self._require_use(actor, field_path=field_path, message=_DESTINATION_DENIED)

    def check_code(
        self,
        actor: SecretActor | None,
        *,
        field_path: tuple[str, ...],
        declares_secret: bool,
        current,
        incoming,
        secret_ids: frozenset | None = None,
    ) -> None:
        """Require USE when code that reads secrets changes what it runs, or what it runs with.

        The declared secrets are handed to the code at run time, so whoever changes
        that code, its inputs (a tool's variables and configs) or its environment (a
        venv's libraries) decides what is done with their plaintext, which is a use of
        them. Code that declares no secret, after the write, may change freely.

        A pinned-org principal changing it must also be allowed to reference every
        secret in `secret_ids`, when given.

        Args:
            declares_secret: Whether the code declares a secret after the write.
            current: The field's persisted value.
            incoming: Its value after the write.

        Raises:
            SecretUseDeniedError: The value changes, the code declares a secret and
                `actor` lacks secrets:USE, or is a pinned-org principal that may not
                reference one of `secret_ids`.
        """
        if not declares_secret or current == incoming:
            return
        self._require_use(actor, field_path=field_path, message=_CODE_DENIED)
        principal = principal_of(actor)
        if (
            secret_ids is not None
            and principal is not None
            and not principal.may_reference_secrets(secret_ids)
        ):
            raise SecretUseDeniedError(field_path=field_path, message=NOT_REFERENCEABLE)

    def _resolve_use(self, actor: SecretActor) -> bool:
        try:
            effective = self._resolver.resolve(user=actor.user, org_id=actor.org_id)
        except OrgMembershipRequiredError:
            return False
        return effective.can(ResourceType.SECRETS.value, Permission.USE)

    def _require_use(
        self, actor: SecretActor | None, *, field_path: tuple[str, ...], message: str
    ) -> None:
        if actor is None:
            logger.warning(
                "SecretUseService denied '{}': no actor, so secrets:USE cannot be resolved.",
                ".".join(field_path),
            )
        if not self.may_use(actor):
            raise SecretUseDeniedError(field_path=field_path, message=message)


def _normalize_destination(value):
    # An omitted, null and empty destination all mean "the provider's default".
    if isinstance(value, tuple):
        return tuple(None if item == "" else item for item in value)
    return None if value == "" else value


secret_use_service = SecretUseService()
