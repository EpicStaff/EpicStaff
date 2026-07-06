"""
Tests for the org-ownership validation of `parent_session_id` on
POST /api/run-session/ (EST-3285 item 5.2 fix).

A `parent_session_id` must only be accepted when the parent Session's graph
belongs to the SAME organization as the graph/session being created (or when
neither graph has an organization at all). This closes the vector where a
tool (subflow_tool) could otherwise link -- and later read back, via the
recursion-guard walk over GET /api/sessions/<id>/ -- a session belonging to
a different organization by simply passing its id as parent_session_id.

NOTE: at the time this test was written, the local dev environment does not
have `django` installed (`ModuleNotFoundError: No module named 'django'`),
which is a pre-existing blocker unrelated to this change -- the whole
`run_session_api_test.py` module is already skipped for the same class of
reason. This test could not be executed locally; the validation logic was
verified by inspection instead (see `RunSession.post` in
`tables/views/views.py`).
"""

import pytest

from django.urls import reverse
from rest_framework import status

from tables.models import (
    Crew,
    CrewNode,
    Edge,
    Graph,
    GraphOrganization,
    Organization,
    Session,
    StartNode,
)
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="org-a")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="org-b")


def _build_runnable_graph(name: str, crew: Crew) -> Graph:
    """Mirrors the `session_data` fixture's graph shape (crew_node +
    start_node + edge) so `create_session_data`/`subgraph_validator` don't
    reject it -- but as a standalone Graph object we can attach a
    GraphOrganization to."""
    graph = Graph.objects.create(name=name)
    crew_node = CrewNode.objects.create(node_name="crew_node_1", crew=crew, graph=graph)
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(
        graph=graph, start_node_id=start_node.id, end_node_id=crew_node.id
    )
    return graph


@pytest.fixture
def graph_in_org_a(crew: Crew, org_a: Organization) -> Graph:
    graph = _build_runnable_graph("graph-in-org-a", crew)
    GraphOrganization.objects.create(graph=graph, organization=org_a)
    return graph


@pytest.fixture
def graph_in_org_b(crew: Crew, org_b: Organization) -> Graph:
    graph = _build_runnable_graph("graph-in-org-b", crew)
    GraphOrganization.objects.create(graph=graph, organization=org_b)
    return graph


@pytest.fixture
def graph_without_org(crew: Crew) -> Graph:
    return _build_runnable_graph("graph-without-org", crew)


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


@pytest.mark.django_db
def test_parent_session_id_accepted_when_neither_graph_has_org(
    auth_client, redis_client_mock, graph_without_org
):
    """When neither the target graph nor the parent session's graph belong to
    any organization, linkage is still allowed (both sides resolve to
    `None` org, i.e. treated as the same "no org" bucket)."""
    url = reverse("run-session")
    parent_session = Session.objects.create(
        graph=graph_without_org, status=Session.SessionStatus.END
    )

    response = auth_client.post(
        url,
        {
            "graph_id": graph_without_org.pk,
            "variables": {},
            "parent_session_id": parent_session.pk,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
