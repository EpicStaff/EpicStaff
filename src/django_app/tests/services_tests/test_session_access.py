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


# ── get_accessible_session ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_member_of_session_org_gets_session(member_a, org_a):
    session = _session(org_a)

    assert get_accessible_session(member_a, session.pk).pk == session.pk


@pytest.mark.django_db
def test_non_member_gets_session_not_found(member_a, org_b):
    with pytest.raises(SessionNotFoundError):
        get_accessible_session(member_a, _session(org_b).pk)


@pytest.mark.django_db
def test_missing_session_gets_session_not_found(member_a):
    with pytest.raises(SessionNotFoundError):
        get_accessible_session(member_a, 987654321)


@pytest.mark.django_db
def test_member_lacking_flows_read_is_denied(no_permissions_a, org_a):
    with pytest.raises(PermissionDenied):
        get_accessible_session(no_permissions_a, _session(org_a).pk)


@pytest.mark.django_db
def test_superadmin_gets_any_orgs_session(superadmin, org_b):
    session = _session(org_b)

    assert get_accessible_session(superadmin, session.pk).pk == session.pk


@pytest.mark.django_db
def test_session_without_graph_gets_session_not_found(superadmin):
    session = Session.objects.create(
        graph=None, status=Session.SessionStatus.PENDING, variables={}
    )
    with pytest.raises(SessionNotFoundError):
        get_accessible_session(superadmin, session.pk)


# ── get_runnable_graph ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_member_gets_graph_by_id_and_by_uuid(member_a, org_a):
    graph = Graph.objects.create(name="H run flow", org=org_a)

    assert get_runnable_graph(member_a, graph_id=graph.pk).pk == graph.pk
    assert get_runnable_graph(member_a, graph_uuid=graph.uuid).pk == graph.pk


@pytest.mark.django_db
def test_non_member_gets_graph_not_found(member_a, org_b):
    graph = Graph.objects.create(name="H foreign flow", org=org_b)

    with pytest.raises(GraphNotFoundError):
        get_runnable_graph(member_a, graph_id=graph.pk)
    with pytest.raises(GraphNotFoundError):
        get_runnable_graph(member_a, graph_uuid=graph.uuid)


@pytest.mark.django_db
def test_missing_graph_gets_graph_not_found(member_a):
    with pytest.raises(GraphNotFoundError):
        get_runnable_graph(member_a, graph_id=987654321)
    with pytest.raises(GraphNotFoundError):
        get_runnable_graph(member_a, graph_uuid=uuid.uuid4())


@pytest.mark.django_db
def test_member_lacking_flows_read_cannot_run_graph(no_permissions_a, org_a):
    graph = Graph.objects.create(name="H locked flow", org=org_a)

    with pytest.raises(PermissionDenied):
        get_runnable_graph(no_permissions_a, graph_id=graph.pk)


@pytest.mark.django_db
def test_superadmin_gets_any_orgs_graph(superadmin, org_b):
    graph = Graph.objects.create(name="H super flow", org=org_b)

    assert get_runnable_graph(superadmin, graph_id=graph.pk).pk == graph.pk
