"""Bulk save writes only into the flow in the URL: an item naming another flow is rejected."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tables.models.graph_models import ConditionalEdge, Edge, GraphNote, PythonNode, StartNode
from tests.fixtures import *  # noqa: F401,F403
from tests.graph_node_builders import create_node
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

_PYTHON_CODE_DATA = {"code": "def main(): return 42", "entrypoint": "main", "libraries": []}

_FOREIGN_GRAPH_ERROR = {"graph": ["Must be this flow."]}


def _save(client, graph: Graph, **lists):
    payload = {"save_version": graph.save_version, **lists}
    return client.post(reverse("graphs-save-flow", args=[graph.id]), payload, format="json")


def _python_node_payload(graph_id, **overrides) -> dict:
    return {"graph": graph_id, "python_code": _PYTHON_CODE_DATA, **overrides}


def _conditional_edge_payload(graph_id, source_node_id) -> dict:
    return {"graph": graph_id, "source_node_id": source_node_id, "python_code": _PYTHON_CODE_DATA}


@pytest.fixture
def other_graph(default_org) -> Graph:
    return Graph.objects.create(name="other flow", org=default_org)


@pytest.mark.django_db
def test_create_into_another_flow_returns_400_and_writes_nothing(auth_client, graph, other_graph):
    other_note = create_node(GraphNote, other_graph)
    other_save_version = other_graph.save_version

    response = _save(
        auth_client,
        graph,
        python_node_list=[_python_node_payload(other_graph.id, uuid=str(other_note.uuid))],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"] == {
        "python_node_list": [{"index": 0, "errors": _FOREIGN_GRAPH_ERROR}]
    }
    assert not PythonNode.objects.filter(graph__in=[graph, other_graph]).exists()
    other_graph.refresh_from_db()
    assert other_graph.save_version == other_save_version


@pytest.mark.django_db
def test_moving_a_node_into_another_flow_returns_400(auth_client, graph, other_graph):
    node = create_node(PythonNode, graph)

    response = _save(
        auth_client,
        graph,
        python_node_list=[_python_node_payload(other_graph.id, id=node.id, node_name="moved")],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"] == {
        "python_node_list": [{"index": 0, "errors": _FOREIGN_GRAPH_ERROR}]
    }
    node.refresh_from_db()
    assert node.graph_id == graph.id
    assert node.node_name != "moved"


@pytest.mark.django_db
def test_edge_into_another_flow_returns_400(auth_client, graph, other_graph):
    start_node, end_node = create_node(StartNode, graph), create_node(PythonNode, graph)

    response = _save(
        auth_client,
        graph,
        edge_list=[
            {"graph": other_graph.id, "start_node_id": start_node.id, "end_node_id": end_node.id}
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"] == {"edge_list": [{"index": 0, "errors": _FOREIGN_GRAPH_ERROR}]}
    assert not Edge.objects.filter(graph__in=[graph, other_graph]).exists()


@pytest.mark.django_db
def test_conditional_edge_into_another_flow_returns_400(auth_client, graph, other_graph):
    source_node = create_node(PythonNode, graph)

    response = _save(
        auth_client,
        graph,
        conditional_edge_list=[_conditional_edge_payload(other_graph.id, source_node.id)],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"] == {
        "conditional_edge_list": [{"index": 0, "errors": _FOREIGN_GRAPH_ERROR}]
    }
    assert not ConditionalEdge.objects.filter(graph__in=[graph, other_graph]).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("as_text", [False, True], ids=["number", "text"])
def test_items_naming_the_saved_flow_are_written(auth_client, graph, as_text):
    graph_id = str(graph.id) if as_text else graph.id
    start_node, end_node = create_node(StartNode, graph), create_node(PythonNode, graph)

    response = _save(
        auth_client,
        graph,
        python_node_list=[_python_node_payload(graph_id, node_name="new")],
        edge_list=[{"graph": graph_id, "start_node_id": start_node.id, "end_node_id": end_node.id}],
        conditional_edge_list=[_conditional_edge_payload(graph_id, end_node.id)],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert PythonNode.objects.filter(graph=graph, node_name="new").exists()
    assert Edge.objects.filter(graph=graph).count() == 1
    assert ConditionalEdge.objects.filter(graph=graph).count() == 1


@pytest.mark.django_db
def test_item_without_graph_is_still_rejected_by_the_serializer(auth_client, graph):
    response = _save(
        auth_client, graph, python_node_list=[{"python_code": _PYTHON_CODE_DATA}]
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    [item_error] = response.data["errors"]["python_node_list"]
    assert "graph" in item_error["errors"]
    assert not PythonNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_foreign_flow_error_is_the_same_for_any_other_flow(client_as, admin_acme, acme, beta):
    acme_graph = Graph.objects.create(name="acme flow", org=acme)
    other_acme_graph = Graph.objects.create(name="other acme flow", org=acme)
    beta_graph = Graph.objects.create(name="beta flow", org=beta)
    missing_graph_id = max(acme_graph.id, other_acme_graph.id, beta_graph.id) + 1000
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    bodies = []
    for foreign_graph_id in (other_acme_graph.id, beta_graph.id, missing_graph_id):
        response = _save(
            client, acme_graph, python_node_list=[_python_node_payload(foreign_graph_id)]
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        bodies.append(response.data["errors"])

    assert bodies == [{"python_node_list": [{"index": 0, "errors": _FOREIGN_GRAPH_ERROR}]}] * 3
    assert not PythonNode.objects.filter(graph=beta_graph).exists()
