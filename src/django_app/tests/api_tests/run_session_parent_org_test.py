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

from rbac.models import Organization, OrganizationUser, Role
from tables.models import Edge, Graph, PythonCode, PythonNode, Session, StartNode
from rbac.models.enums import BuiltInRole
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


def _build_runnable_graph(name: str, org: Organization) -> Graph:
    """A start node wired to a python node: without an edge off the start node
    `create_session_data` raises GraphEntryPointException and the run never
    reaches the parent-link outcome under test."""
    graph = Graph.objects.create(name=name, org=org)
    start_node = StartNode.objects.create(graph=graph, variables={})
    python_code = PythonCode.objects.create(code="def main():\n    return 1\n")
    python_node = PythonNode.objects.create(
        graph=graph, python_code=python_code, node_name="python_node"
    )
    Edge.objects.create(
        graph=graph, start_node_id=start_node.pk, end_node_id=python_node.pk
    )
    return graph


@pytest.fixture
def graph_in_org_a(org_a: Organization) -> Graph:
    return _build_runnable_graph("graph-in-org-a", org_a)


@pytest.fixture
def graph_in_org_b(org_b: Organization) -> Graph:
    return _build_runnable_graph("graph-in-org-b", org_b)


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
    assert response.data["code"] == "parent_session_not_found"
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
    assert response.data["code"] == "parent_session_not_found"
    assert not Session.objects.filter(graph=graph_in_org_a).exists()


@pytest.mark.django_db
def test_cross_org_and_nonexistent_parent_get_the_same_response(
    auth_client, redis_client_mock, graph_in_org_a, session_in_org_b
):
    url = reverse("run-session")

    def run_with_parent(parent_session_id: int):
        return auth_client.post(
            url,
            {
                "graph_id": graph_in_org_a.pk,
                "variables": {},
                "parent_session_id": parent_session_id,
            },
            format="json",
        )

    cross_org_response = run_with_parent(session_in_org_b.pk)
    nonexistent_response = run_with_parent(session_in_org_b.pk + 10_000)

    assert cross_org_response.status_code == status.HTTP_400_BAD_REQUEST
    assert nonexistent_response.status_code == status.HTTP_400_BAD_REQUEST
    assert cross_org_response.data == nonexistent_response.data == {
        "status_code": 400,
        "code": "parent_session_not_found",
        "message": "Parent session not found.",
    }
