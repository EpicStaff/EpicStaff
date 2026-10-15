import uuid

import pytest
from rest_framework.exceptions import PermissionDenied

from tables.exceptions import GraphNotFoundError, SessionNotFoundError
from tables.models import Graph
from tables.models.session_models import Session
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from tables.services.session_access import get_accessible_session, get_runnable_graph


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
    assert {"graph_schema", "variables", "status_data"} <= accessible.get_deferred_fields()


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
