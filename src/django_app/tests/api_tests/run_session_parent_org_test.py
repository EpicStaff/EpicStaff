"""
Tests for the org-ownership validation of `parent_session_id` on
POST /api/run-session/.

A `parent_session_id` must only be accepted when the parent Session's graph
belongs to the SAME organization as the graph/session being created. This
closes the vector where a tool (subflow_tool) could otherwise link -- and
later read back, via the recursion-guard walk over GET /api/sessions/<id>/ --
a session belonging to a different organization by simply passing its id as
parent_session_id.

NOTE: rewritten for RBAC org-scoping (main). Graph.org is now a
required FK (see migrations 0185/0186) and is the sole org boundary enforced
by `RunSession.post` -- the older `GraphOrganization` model is unrelated to
org ownership post-RBAC (it only carries persistent "user_variables" for a
flow) so it is no longer used to establish the org boundary in this test.
"""

import pytest

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models import (
    Crew,
    CrewNode,
    Edge,
    Graph,
    Organization,
    OrganizationUser,
    Role,
    Session,
    StartNode,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="parent-org-a")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="parent-org-b")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="parent_session_member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def auth_client(member_a, org_a):
    """A member of org_a only -- single-org membership needs no active-org
    header for the RBAC context resolver to pick org_a."""
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _build_runnable_graph(name: str, crew: Crew, org: Organization) -> Graph:
    """Mirrors the `session_data` fixture's graph shape (crew_node +
    start_node + edge) so `create_session_data`/`subgraph_validator` don't
    reject it."""
    graph = Graph.objects.create(name=name, org=org)
    crew_node = CrewNode.objects.create(node_name="crew_node_1", crew=crew, graph=graph)
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(
        graph=graph, start_node_id=start_node.id, end_node_id=crew_node.id
    )
    return graph


@pytest.fixture
def graph_in_org_a(crew: Crew, org_a: Organization) -> Graph:
    return _build_runnable_graph("graph-in-org-a", crew, org_a)


@pytest.fixture
def graph_in_org_b(crew: Crew, org_b: Organization) -> Graph:
    return _build_runnable_graph("graph-in-org-b", crew, org_b)


@pytest.fixture
def session_in_org_a(graph_in_org_a) -> Session:
    return Session.objects.create(
        graph=graph_in_org_a, status=Session.SessionStatus.END
    )


@pytest.fixture
def session_in_org_b(graph_in_org_b) -> Session:
    return Session.objects.create(
        graph=graph_in_org_b, status=Session.SessionStatus.END
    )


@pytest.mark.django_db
def test_cross_org_parent_session_id_is_rejected(
    auth_client, redis_client_mock, graph_in_org_a, session_in_org_b
):
    """A parent_session_id from a different org's session must be rejected
    with a 400 and must NOT create/link the new Session."""
    url = reverse("run-session")

    response = auth_client.post(
        url,
        {
            "graph_id": graph_in_org_a.pk,
            "variables": {},
            "parent_session_id": session_in_org_b.pk,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert not Session.objects.filter(parent_session_id=session_in_org_b.pk).exists()


@pytest.mark.django_db
def test_same_org_parent_session_id_is_accepted(
    auth_client, redis_client_mock, graph_in_org_a, session_in_org_a
):
    """A parent_session_id from the SAME org's session must be accepted and
    linked via Session.parent_session."""
    url = reverse("run-session")

    response = auth_client.post(
        url,
        {
            "graph_id": graph_in_org_a.pk,
            "variables": {},
            "parent_session_id": session_in_org_a.pk,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_session_id = response.data["session_id"]
    new_session = Session.objects.get(pk=new_session_id)
    assert new_session.parent_session_id == session_in_org_a.pk


@pytest.mark.django_db
def test_nonexistent_parent_session_id_is_rejected(
    auth_client, redis_client_mock, graph_in_org_a
):
    url = reverse("run-session")

    response = auth_client.post(
        url,
        {
            "graph_id": graph_in_org_a.pk,
            "variables": {},
            "parent_session_id": 999999,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
