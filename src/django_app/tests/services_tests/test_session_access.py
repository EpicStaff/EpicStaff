import uuid

import pytest
from rest_framework.exceptions import PermissionDenied

from tables.exceptions import GraphNotFoundError, SessionNotFoundError
from tables.models import Graph
from tables.models.session_models import Session
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from tables.services.session_access import (
    assert_graph_readable,
    get_accessible_session,
    get_runnable_graph,
)
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import role_viewer  # noqa: F401


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="H-Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="H-Org B")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="h_member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def no_permissions_a(db, django_user_model, org_a):
    role = Role.objects.create(name="H-NoPerms", org=org_a, is_built_in=False)
    user = django_user_model.objects.create_user(
        email="h_no_perms_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    return user


@pytest.fixture
def flows_reader_a(custom_role_member, org_a):
    return custom_role_member(org_a, {ResourceType.FLOWS: Permission.READ}, "h-reader")


@pytest.fixture
def flows_runner_a(custom_role_member, org_a):
    return custom_role_member(
        org_a, {ResourceType.FLOWS: Permission.READ | Permission.USE}, "h-runner"
    )


@pytest.fixture
def superadmin(db, django_user_model):
    return django_user_model.objects.create_superuser(
        email="h_super@example.com", password="StrongPass123!"
    )


def _session(org):
    graph = Graph.objects.create(name="H flow", org=org)
    return Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )


def _missing_session(org):
    return 987654321


def _graphless_session(org):
    return Session.objects.create(graph=None, status=Session.SessionStatus.PENDING, variables={}).pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "target_org", "make_session", "outcome"),
    [
        ("member_a", "org_a", lambda org: _session(org).pk, "granted"),
        # Another org's session looks exactly like a missing one.
        ("member_a", "org_b", lambda org: _session(org).pk, SessionNotFoundError),
        ("member_a", "org_a", _missing_session, SessionNotFoundError),
        ("no_permissions_a", "org_a", lambda org: _session(org).pk, PermissionDenied),
        ("superadmin", "org_b", lambda org: _session(org).pk, "granted"),
        ("superadmin", "org_b", _graphless_session, SessionNotFoundError),
    ],
    ids=["own-org", "other-org", "missing", "no-flows-read", "superadmin-any-org", "no-graph"],
)
def test_get_accessible_session(request, caller, target_org, make_session, outcome):
    user = request.getfixturevalue(caller)
    session_id = make_session(request.getfixturevalue(target_org))

    if outcome == "granted":
        assert get_accessible_session(user, session_id).pk == session_id
    else:
        with pytest.raises(outcome):
            get_accessible_session(user, session_id)


@pytest.mark.django_db
def test_accessible_session_loads_only_id_and_status(member_a, org_a):
    session = _session(org_a)

    accessible = get_accessible_session(member_a, session.pk)

    assert accessible.status == Session.SessionStatus.PENDING
    assert {"variables", "status_data"} <= accessible.get_deferred_fields()


@pytest.mark.django_db
@pytest.mark.parametrize("lookup", ["graph_id", "graph_uuid"])
@pytest.mark.parametrize(
    ("caller", "target_org", "outcome"),
    [
        ("member_a", "org_a", "granted"),
        ("member_a", "org_b", GraphNotFoundError),
        ("member_a", None, GraphNotFoundError),
        ("no_permissions_a", "org_a", PermissionDenied),
        ("superadmin", "org_b", "granted"),
    ],
    ids=["own-org", "other-org", "missing", "no-flows-read", "superadmin-any-org"],
)
def test_get_runnable_graph(request, lookup, caller, target_org, outcome):
    user = request.getfixturevalue(caller)
    if target_org is None:
        key = 987654321 if lookup == "graph_id" else uuid.uuid4()
    else:
        graph = Graph.objects.create(name="H run flow", org=request.getfixturevalue(target_org))
        key = graph.pk if lookup == "graph_id" else graph.uuid

    if outcome == "granted":
        assert get_runnable_graph(user, **{lookup: key}).pk == graph.pk
    else:
        with pytest.raises(outcome):
            get_runnable_graph(user, **{lookup: key})


# ── flows:USE ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "target_org", "outcome"),
    [
        ("flows_runner_a", "org_a", "granted"),
        ("flows_reader_a", "org_a", PermissionDenied),
        # Another org's graph is a 404 whether or not the caller holds USE.
        ("flows_runner_a", "org_b", GraphNotFoundError),
        ("flows_reader_a", "org_b", GraphNotFoundError),
    ],
    ids=["use", "read-without-use", "use-other-org", "read-other-org"],
)
def test_running_a_graph_needs_flows_use(request, caller, target_org, outcome):
    user = request.getfixturevalue(caller)
    graph = Graph.objects.create(name="H run flow", org=request.getfixturevalue(target_org))

    if outcome == "granted":
        assert get_runnable_graph(user, graph_id=graph.pk).pk == graph.pk
    else:
        with pytest.raises(outcome):
            get_runnable_graph(user, graph_id=graph.pk)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "target_org", "action", "outcome"),
    [
        ("flows_reader_a", "org_a", None, "granted"),
        ("flows_reader_a", "org_a", Permission.USE, PermissionDenied),
        ("flows_runner_a", "org_a", Permission.USE, "granted"),
        # Another org's session is a 404 whether or not the caller holds USE.
        ("flows_runner_a", "org_b", Permission.USE, SessionNotFoundError),
        ("flows_reader_a", "org_b", Permission.USE, SessionNotFoundError),
    ],
    ids=["read-default", "read-for-use", "use-for-use", "use-other-org", "read-other-org"],
)
def test_session_access_for_use_needs_flows_use(request, caller, target_org, action, outcome):
    user = request.getfixturevalue(caller)
    session_id = _session(request.getfixturevalue(target_org)).pk
    arguments = (user, session_id) if action is None else (user, session_id, action)

    if outcome == "granted":
        assert get_accessible_session(*arguments).pk == session_id
    else:
        with pytest.raises(outcome):
            get_accessible_session(*arguments)


# ── graph co-editing: flows:READ on the graph's own org ─────────────────────


@pytest.fixture
def viewer_a(db, django_user_model, org_a, role_viewer):
    user = django_user_model.objects.create_user(
        email="h_viewer_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_viewer)
    return user


@pytest.fixture
def member_a_without_flows(custom_role_member, org_a):
    return custom_role_member(org_a, {ResourceType.AGENTS: Permission.READ}, "h-no-flows-a")


def _graph_of_a(org_a, org_b):
    return Graph.objects.create(name="H collab flow", org=org_a).pk


def _graph_of_b(org_a, org_b):
    return Graph.objects.create(name="H collab flow", org=org_b).pk


def _missing_graph(org_a, org_b):
    return 987654321


def _binned_graph_of_a(org_a, org_b):
    graph = Graph.objects.create(name="H binned flow", org=org_a)
    graph.delete()
    return graph.pk


def _graph_of_deactivated_a(org_a, org_b):
    graph_id = _graph_of_a(org_a, org_b)
    Organization.objects.filter(pk=org_a.pk).update(is_active=False)
    return graph_id


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("caller", "make_graph", "outcome"),
    [
        ("viewer_a", _graph_of_a, "granted"),
        ("viewer_a", _missing_graph, GraphNotFoundError),
        ("viewer_a", _binned_graph_of_a, GraphNotFoundError),
        # Another org's graph looks exactly like a missing one.
        ("viewer_a", _graph_of_b, GraphNotFoundError),
        ("viewer_a", _graph_of_deactivated_a, GraphNotFoundError),
        ("member_a_without_flows", _graph_of_a, PermissionDenied),
        ("superadmin", _graph_of_b, "granted"),
    ],
    ids=[
        "viewer-own-org",
        "missing",
        "recycle-binned",
        "other-org",
        "inactive-org",
        "no-flows-read",
        "superadmin-without-membership",
    ],
)
def test_assert_graph_readable(request, org_a, org_b, caller, make_graph, outcome):
    user = request.getfixturevalue(caller)
    graph_id = make_graph(org_a, org_b)

    if outcome == "granted":
        assert_graph_readable(user, graph_id)
    else:
        with pytest.raises(outcome):
            assert_graph_readable(user, graph_id)
