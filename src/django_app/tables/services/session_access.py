from rbac.access.resolver import PermissionResolver
from rbac.models.enums import Permission, ResourceType
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from tables.models import Session

_resolver = PermissionResolver()


def assert_session_org_access(user, session, action: Permission = Permission.READ):
    """Authorize a user against a session via the org that owns its graph.

    Sessions are scoped as children of their graph, so the session's
    organization is `session.graph.org`. Used by the non-ViewSet session
    surfaces (run-session SSE stream, get-updates, stop) which cannot rely on
    HasOrgPermission (no DRF `action`) or the X-Organization-Id header (SSE).

    Raises:
        NotFound: the session has no graph (cannot resolve an org).
        OrgMembershipRequiredError (403): caller is not a member of the org
            and is not a superadmin.
        PermissionDenied (403): the caller's role lacks `action` on FLOWS.

    Superadmin passes unconditionally (PermissionResolver bypass).
    """
    if session.graph_id is None:
        raise NotFound()
    effective = _resolver.resolve(user=user, org_id=session.graph.org_id)
    if not effective.can(ResourceType.FLOWS, action):
        raise PermissionDenied("You do not have permission to access this session.")


def assert_parent_session_in_org(parent_session_id: int, org_id: int) -> None:
    """Reject a parent session that does not belong to the organization `org_id`.

    A sub-session is deleted together with its parent (`Session.parent_session`
    cascades), so a parent in another organization would let that organization
    delete this one. A missing parent and another organization's parent raise
    the same error, so the response never reveals that a session id exists.

    Raises:
        ValidationError (400): no session with this id in the organization.
    """
    if not Session.objects.filter(id=parent_session_id, graph__org_id=org_id).exists():
        raise ValidationError({"parent_session_id": ["Parent session not found."]})
