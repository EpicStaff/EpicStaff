"""Principals that act in exactly one organization without being a `User`.

`rbac` resolves permissions and the active org for such a principal through
`PinnedOrgPrincipal` alone, so it never imports the app that defines one. Code
that needs a human reads `acting_person`, never an id of the principal: a
pinned principal has no `id`, `pk` or `email`, so a call site that assumes a
`User` fails loudly instead of attributing work to whichever user shares a
synthetic id.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from django.contrib.auth import get_user_model

from rbac.access.effective import EffectivePermissions

if TYPE_CHECKING:
    from django.db.models import Model
    from tables.models.user import User


@runtime_checkable
class PinnedOrgPrincipal(Protocol):
    """A non-`User` caller pinned to one organization, carrying its own permissions.

    `PermissionResolver` resolves its permissions with
    `resolve_effective_permissions` in `pinned_org_id` and treats every other
    org as one it is not a member of. `OrgContextService` resolves its active
    org to `pinned_org_id` and refuses any other.

    Attributes:
        is_plugin_credential: True when the principal authenticated with a
            plugin credential; person-only surfaces refuse it.
        pinned_org_id: The only organization the principal acts in.
        plugin_identifier: The plugin the principal acts for.
        display_name: Shown wherever an editor or actor is named.
        person: The user the call is made on behalf of, or None.
        rate_limit_key: Stable throttle bucket key; never derived from a user id.
    """

    is_plugin_credential: bool
    pinned_org_id: int
    plugin_identifier: str
    display_name: str
    person: "User | None"
    rate_limit_key: str

    def resolve_effective_permissions(self, org_id: int) -> EffectivePermissions: ...

    def may_reference_secrets(self, secret_ids: frozenset[int]) -> bool:
        """Return whether a row the principal writes may reference every one of `secret_ids`.

        Asked by `SecretReferenceGuard` for each secret reference of every row the
        principal creates or changes, on top of `secrets: use`. A row that references a
        secret also says where its value is sent (an LLM config's `base_url`, a Python
        node's code), so a principal that could reference any of the organization's
        secrets could send their values anywhere.
        """
        ...

    def owns(self, instance: "Model") -> bool:
        """Return whether the principal created `instance`, a row that still exists.

        Asked by `SecretDestinationGuard` before the principal changes where a model row
        sends the keys of the organization's configs that use it: only its own rows.
        """
        ...


def is_pinned_org_principal(user: object) -> bool:
    """Return whether `user` implements `PinnedOrgPrincipal`."""
    return isinstance(user, PinnedOrgPrincipal)


def is_plugin_credential(request) -> bool:
    """Return whether the request authenticated with a plugin credential.

    Either the credential (`request.auth`) or the principal (`request.user`)
    may carry the flag; only a literal True counts, so an object answering
    every attribute lookup never qualifies.
    """
    credential = getattr(request, "auth", None)
    principal = getattr(request, "user", None)
    return (
        getattr(credential, "is_plugin_credential", False) is True
        or getattr(principal, "is_plugin_credential", False) is True
    )


def acting_person(user: object) -> "User | None":
    """Return the human a call is made by or for.

    The user itself for a `User`, the on-behalf-of person for a pinned
    principal (None when it acts on its own), and None for every other
    principal (anonymous, the system API key).
    """
    if isinstance(user, get_user_model()):
        return user
    if is_pinned_org_principal(user):
        return user.person
    return None
