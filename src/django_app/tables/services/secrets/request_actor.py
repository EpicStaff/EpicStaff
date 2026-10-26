from rbac.exceptions import (
    OrganizationNotFoundError,
    OrgContextRequiredError,
    OrgMembershipRequiredError,
)
from rbac.scoping.fields import resolve_active_org_id
from tables.services.secrets.pinned_principal_rules import pinned_principal_of_request
from tables.services.secrets.secret_use_service import SecretActor

_ACTOR_ATTRIBUTE = "_secret_use_actor"


def actor_from_request(request) -> SecretActor | None:
    """Return who is writing and in which org their secrets:USE is looked up.

    Returns None when there is no request or no authenticated user, which the
    secret Use service denies whenever a write needs Use.

    The org is resolved here, before anyone knows whether the write needs Use, so
    a request without a usable active org must not fail a write that needs none:
    the actor then carries `org_id=None`, which the service treats as "no Use"
    unless the user is a superadmin. Writes that need an org still fail on their
    own org resolution with the usual 400/403/404.

    The actor is kept on the request, so secrets:USE is resolved at most once per
    request however many rows it writes (a graph bulk save).

    Raises:
        IncompletePluginCredentialError: The request authenticated with a plugin credential whose
            user does not implement `PinnedOrgPrincipal`; such a caller is refused,
            never taken for a person.
    """
    if request is None:
        return None
    pinned_principal_of_request(request)
    actor = getattr(request, _ACTOR_ATTRIBUTE, None)
    if actor is not None:
        return actor
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        org_id = resolve_active_org_id(request)
    except (OrgContextRequiredError, OrgMembershipRequiredError, OrganizationNotFoundError):
        org_id = None
    actor = SecretActor(user=user, org_id=org_id, use_memo=[])
    setattr(request, _ACTOR_ATTRIBUTE, actor)
    return actor
