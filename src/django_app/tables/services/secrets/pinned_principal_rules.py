"""The extra secret rules for a pinned-org principal (a plugin's service account).

A row that references a secret also says where its value goes, so on top of secrets:USE
a pinned-org principal may reference only the secrets it may reference
(`PinnedOrgPrincipal.may_reference_secrets`), may not let a header marker bind to any
other secret when work it starts resolves the marker, and never sets where a model
configuration sends requests. People are not limited by any of these rules.

`SecretUseService` applies the reference rules to every write it checks, and the run-start
rule is called where work starts. The endpoint rule guards a config's `connection` and
lives in `secret_use_checks`, which the API and the import both run.
"""

from rbac.access.principals import is_pinned_org_principal, is_plugin_credential
from tables.models import Secret
from tables.services.secrets.exceptions import (
    IncompletePluginCredentialError,
    SecretMarkerNotReferenceableError,
)
from utils.logger import logger

# Name no secret: the caller may not even know which one the row references.
NOT_REFERENCEABLE = (
    "This credential can reference only secrets it created, so it cannot save a row "
    "that references any other secret."
)


def pinned_principal_of_user(user):
    """Return `user` when it is a pinned-org principal, None for anyone else.

    Fails closed: a caller that carries the plugin-credential flag but does not implement
    `PinnedOrgPrincipal` is refused, never taken for a person whose writes nothing limits.

    Raises:
        IncompletePluginCredentialError: The caller is a plugin credential without the
            protocol.
    """
    if is_pinned_org_principal(user):
        return user
    if getattr(user, "is_plugin_credential", False) is True:
        _refuse_incomplete_principal(user)
    return None


def pinned_principal_of_request(request):
    """The request's pinned-org principal, or None for a person and without a request.

    Raises:
        IncompletePluginCredentialError: The request authenticated with a plugin
            credential whose user does not implement `PinnedOrgPrincipal`.
    """
    if request is None:
        return None
    user = getattr(request, "user", None)
    principal = pinned_principal_of_user(user)
    if principal is None and is_plugin_credential(request):
        _refuse_incomplete_principal(user)
    return principal


def may_reference_marker_names(*, principal, names) -> bool:
    """Whether every one of `names` is a secret `principal` may reference.

    A marker binds by name when a run starts, not by id when it is written. So every
    non-system secret of the organization with that name counts, binned ones too (a
    restore makes one the name's secret again), and a name no secret has is refused:
    a person could create a secret of that name later and the run would send it.
    Finding the secrets is one query for any number of names, and none for an
    empty `names`.
    """
    if not names:
        return True
    named_secrets = dict(
        Secret.all_objects.filter(
            org_id=principal.pinned_org_id, name__in=names, system=False
        ).values_list("pk", "name")
    )
    return set(names) <= set(named_secrets.values()) and principal.may_reference_secrets(
        frozenset(named_secrets)
    )


def assert_may_resolve_markers(*, principal, names) -> None:
    """Refuse work `principal` starts that resolves a marker it may not reference.

    Asked when a run or an indexing job starts, as well as when a row is written: a marker
    binds by name, so between the write and the start its name may come to mean another
    secret (the plugin's own secret purged, and a person's created under the same name).
    The rule is `may_reference_marker_names`.

    Raises:
        SecretMarkerNotReferenceableError: One of `names` is not a secret `principal` may
            reference; the message names no secret.
    """
    if not may_reference_marker_names(principal=principal, names=names):
        raise SecretMarkerNotReferenceableError()


def _refuse_incomplete_principal(user) -> None:
    logger.error(
        "A plugin credential's user ({}) does not implement PinnedOrgPrincipal; its write "
        "was refused",
        type(user).__name__,
    )
    raise IncompletePluginCredentialError()
