from rest_framework.exceptions import NotFound, PermissionDenied

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.permission_resolver import PermissionResolver

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
