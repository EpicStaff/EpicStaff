from uuid import UUID

from django.db.models import F
from rbac.access.asserts import assert_row_org_permission
from rbac.models.enums import Permission, ResourceType
from tables.exceptions import (
    GraphNotFoundError,
    ParentSessionNotFoundError,
    SessionNotFoundError,
)
from tables.models import Graph, Session


def get_accessible_session(user, session_id: int, action: Permission = Permission.READ) -> Session:
    """Fetch a session by raw id and authorize `user` via the org that owns its graph.

    For the non-ViewSet session surfaces (run-session SSE stream, get-updates, stop),
    which cannot rely on HasOrgPermission (no DRF `action`) or the X-Organization-Id
    header (SSE). A missing session, a session without a graph and a session in an
    org the caller is not a member of all raise the same SessionNotFoundError.
    Superadmin passes unconditionally (PermissionResolver bypass).

    Raises:
        SessionNotFoundError (404): no session the caller may know about.
        PermissionDenied (403): a member of the owning org whose role lacks `action`
            on FLOWS.
    """
    session = (
        Session.objects.annotate(owner_org_id=F("graph__org_id")).filter(pk=session_id).first()
    )
    if session is None or session.owner_org_id is None:
        raise SessionNotFoundError()
    assert_row_org_permission(
        user,
        session.owner_org_id,
        ResourceType.FLOWS,
        action,
        not_found=SessionNotFoundError(),
    )
    return session


def get_runnable_graph(
    user, *, graph_id: int | None = None, graph_uuid: UUID | None = None
) -> Graph:
    """Fetch the graph to run by id (or uuid when no id is given) and authorize `user`.

    Running a flow requires READ on FLOWS within the graph's own org. A missing graph
    and a graph in an org the caller is not a member of raise the same
    GraphNotFoundError. Superadmin passes unconditionally.

    Raises:
        GraphNotFoundError (404): no graph the caller may know about.
        PermissionDenied (403): a member of the owning org whose role lacks READ on FLOWS.
    """
    lookup = {"id": graph_id} if graph_id else {"uuid": graph_uuid}
    graph = Graph.objects.filter(**lookup).first()
    if graph is None:
        raise GraphNotFoundError()
    assert_row_org_permission(
        user,
        graph.org_id,
        ResourceType.FLOWS,
        Permission.READ,
        not_found=GraphNotFoundError(),
    )
    return graph


def assert_parent_session_in_org(parent_session_id: int, org_id: int) -> None:
    """Reject a parent session that does not belong to the organization `org_id`.

    A sub-session is deleted together with its parent (`Session.parent_session`
    cascades), so a parent in another organization would let that organization
    delete this one. A missing parent and another organization's parent raise
    the same error, so the response never reveals that a session id exists.

    Raises:
        ParentSessionNotFoundError (400): no session with this id in the organization.
    """
    if not Session.objects.filter(id=parent_session_id, graph__org_id=org_id).exists():
        raise ParentSessionNotFoundError()
