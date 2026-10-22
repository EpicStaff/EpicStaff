from dataclasses import dataclass

from rbac.access.resolver import PermissionResolver
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models.enums import Permission, ResourceType
from tables.services.secrets.exceptions import SecretUseDeniedError
from tables.services.secrets.linked_ids import linked_ids
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
    """Who is writing, and in which organization their secrets:USE is looked up."""

    user: object
    org_id: int | None


class SecretUseService:
    """Decides whether a write needs secrets:USE, and denies it when the actor lacks it.

    Every check compares the persisted value with the value after the write, so a
    resend of what is already stored needs no permission. Knows nothing about
    requests or serializers: callers pass plain values and let SecretUseDeniedError
    propagate to the exception handler, or render it in their own shape (bulk save).
    """

    def __init__(self, resolver=None):
        self._resolver = resolver or PermissionResolver()

    def may_use(self, actor: SecretActor | None) -> bool:
        """Return whether `actor` holds secrets:USE in its organization; no actor or no membership is False."""
        if actor is None:
            return False
        try:
            effective = self._resolver.resolve(user=actor.user, org_id=actor.org_id)
        except OrgMembershipRequiredError:
            return False
        return effective.can(ResourceType.SECRETS.value, Permission.USE)

    def check_references(
        self, actor: SecretActor | None, *, field_path: tuple[str, ...], current, incoming
    ) -> None:
        """Require USE when the set of linked secrets changes, including set to empty.

        Args:
            current: What the row links to now: None, a row, a pk, a related manager
                (binned rows count) or an iterable of rows or pks.
            incoming: What it will link to after the write, in any of the same forms.

        Raises:
            SecretUseDeniedError: The set changes and `actor` lacks secrets:USE.
        """
        if linked_ids(current) == linked_ids(incoming):
            return
        self._require_use(actor, field_path=field_path, message=_DENIED)

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

        Raises:
            SecretUseDeniedError: A new marker name appears and `actor` lacks secrets:USE.
        """
        added = extract_secret_marker_names(incoming_headers) - extract_secret_marker_names(
            current_headers
        )
        if not added:
            return
        self._require_use(actor, field_path=field_path, message=_DENIED)

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
