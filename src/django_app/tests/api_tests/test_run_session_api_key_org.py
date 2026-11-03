"""A USER API key runs, stops and reads the status of sessions of its own org only.

The key's owner may be a member of other orgs, or a superadmin of every org; the
key still sees another org's graph or session exactly like a missing one.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from rbac.models import OrganizationUser
from tables.models import Edge, Graph, PythonCode, PythonNode, Session, StartNode
from tests.fixtures import redis_client_mock  # noqa: F401
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

MISSING_ID = 987654321


@pytest.fixture
def member_of_both(member_only, beta, role_member):
    """Member (flows USE) of Acme, from `member_only`, and of Beta."""
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


@pytest.fixture(params=["member_of_both", "superadmin"])
def acme_key_client(request, issue_api_key, acme):
    raw_key, _ = issue_api_key(user=request.getfixturevalue(request.param), org=acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)
    return client


def _runnable_graph(org):
    graph = Graph.objects.create(name=f"{org.name} flow", org=org)
    start = StartNode.objects.create(graph=graph, variables={})
    node = PythonNode.objects.create(
        graph=graph,
        node_name="first",
        python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n"),
    )
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=node.pk)
    return graph


def _session(org):
    graph = Graph.objects.create(name=f"{org.name} session flow", org=org)
    return Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)


@pytest.mark.django_db
def test_key_cannot_run_a_flow_of_another_org(acme_key_client, beta, redis_client_mock):
    graph = _runnable_graph(beta)

    response = acme_key_client.post(reverse("run-session"), {"graph_id": graph.pk}, format="json")
    missing = acme_key_client.post(reverse("run-session"), {"graph_id": MISSING_ID}, format="json")

    assert response.status_code == 404, response.content
    assert response.json() == missing.json()
    assert not Session.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_key_runs_a_flow_of_its_own_org(acme_key_client, acme, redis_client_mock):
    graph = _runnable_graph(acme)

    response = acme_key_client.post(reverse("run-session"), {"graph_id": graph.pk}, format="json")

    assert response.status_code == 201, response.content
    assert Session.objects.get(pk=response.json()["session_id"]).graph_id == graph.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route", "method"), [("stop-session", "post"), ("get-updates", "get")]
)
def test_key_cannot_touch_a_session_of_another_org(
    acme_key_client, beta, route, method, redis_client_mock
):
    session = _session(beta)
    call = getattr(acme_key_client, method)

    response = call(reverse(route, kwargs={"session_id": session.pk}))
    missing = call(reverse(route, kwargs={"session_id": MISSING_ID}))

    assert response.status_code == 404, response.content
    assert response.json() == missing.json()
    redis_client_mock.publish.assert_not_called()
    session.refresh_from_db()
    assert session.status == Session.SessionStatus.RUN


@pytest.mark.django_db
def test_key_reads_the_status_of_its_own_orgs_session(acme_key_client, acme):
    session = _session(acme)

    response = acme_key_client.get(reverse("get-updates", kwargs={"session_id": session.pk}))

    assert response.status_code == 200, response.content
    assert response.json() == {"status": Session.SessionStatus.RUN}


@pytest.mark.django_db
def test_key_stops_its_own_orgs_session(acme_key_client, acme, redis_client_mock):
    session = _session(acme)

    response = acme_key_client.post(reverse("stop-session", kwargs={"session_id": session.pk}))

    assert response.status_code == 204, response.content
    redis_client_mock.publish.assert_called()
