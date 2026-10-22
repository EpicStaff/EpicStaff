"""GET /api/pythonnodes/<pk>/last-session-input/ — the node's input from its latest finished run.

Session messages are stored under the node's runtime name ("Name #N #id"), so
the lookup must build exactly that string; the frontend input map asks for it.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.models import Graph, PythonCode
from tables.models.graph_models import GraphSessionMessage, PythonNode
from tables.models.session_models import Session
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _python_node(graph: Graph) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph,
        node_name="Py",
        node_number=3,
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )


def _finished_run_message(graph: Graph, name: str, node_input: dict, minutes_ago: int) -> None:
    created_at = timezone.now() - timedelta(minutes=minutes_ago)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.END, variables={})
    Session.objects.filter(pk=session.pk).update(created_at=created_at)
    GraphSessionMessage.objects.create(
        session=session,
        created_at=created_at,
        name=name,
        message_data={"message_type": "start", "input": node_input},
        uuid=uuid4(),
    )


def _url(node: PythonNode) -> str:
    return reverse("python-node-last-session-input", kwargs={"pk": node.pk})


@pytest.mark.django_db
def test_returns_the_input_recorded_under_the_numbered_runtime_name(acme, acme_client):
    graph = Graph.objects.create(name="flow", org=acme)
    node = _python_node(graph)
    _finished_run_message(graph, f"Py #3 #{node.pk}", {"x": 1}, minutes_ago=5)
    # Newer, but "Name #id" without the number is not this node's runtime name.
    _finished_run_message(graph, f"Py #{node.pk}", {"x": 2}, minutes_ago=1)

    response = acme_client.get(_url(node))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["input"] == {"x": 1}


@pytest.mark.django_db
def test_returns_null_input_when_the_node_never_finished_a_run(acme, acme_client):
    node = _python_node(Graph.objects.create(name="flow", org=acme))

    response = acme_client.get(_url(node))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["input"] is None


@pytest.mark.django_db
def test_python_node_in_another_org_is_not_found(acme_client, beta):
    graph = Graph.objects.create(name="beta flow", org=beta)
    node = _python_node(graph)
    _finished_run_message(graph, f"Py #3 #{node.pk}", {"secret": "beta"}, minutes_ago=1)

    response = acme_client.get(_url(node))

    assert response.status_code == status.HTTP_404_NOT_FOUND
