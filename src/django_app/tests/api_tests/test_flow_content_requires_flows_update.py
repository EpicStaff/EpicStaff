"""Writing a flow's nodes and edges through their own endpoints needs flows:UPDATE.

Adding, changing or removing a node or an edge edits the flow, so it needs the same
bit as the bulk save. flows:CREATE and flows:DELETE gate the flow itself, not its
content.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode
from tables.models.graph_models import DecisionTableNode, Edge, PythonNode
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

READ_CREATE = Permission.READ | Permission.CREATE
READ_DELETE = Permission.READ | Permission.DELETE
READ_UPDATE = Permission.READ | Permission.UPDATE


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="flow-content-acme", org=acme)


def _python_node(graph, name="py"):
    return PythonNode.objects.create(
        graph=graph,
        node_name=name,
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )


def _edge(graph):
    return Edge.objects.create(
        graph=graph,
        start_node_id=_python_node(graph, "from").id,
        end_node_id=_python_node(graph, "to").id,
    )


def _python_node_payload(graph):
    return {
        "graph": graph.id,
        "node_name": "new",
        "python_code": {"code": "def main(**kwargs): ...", "entrypoint": "main"},
    }


def _edge_payload(graph):
    return {
        "graph": graph.id,
        "start_node_id": _python_node(graph, "from").id,
        "end_node_id": _python_node(graph, "to").id,
        "metadata": {},
    }


def _decision_table_payload(graph):
    return {"graph": graph.id, "node_name": "decide", "condition_groups": []}


CREATE_ROUTES = [
    pytest.param("pythonnode-list", PythonNode, _python_node_payload, id="python-node"),
    pytest.param("edge-list", Edge, _edge_payload, id="edge"),
    # A separate write path: its create() override skips perform_create.
    pytest.param(
        "decisiontablenode-list", DecisionTableNode, _decision_table_payload, id="decision-table"
    ),
]

# Every viewset over a flow's content, by route basename.
FLOW_CONTENT_BASENAMES = [
    "pythonnode",
    "fileextractornode",
    "knowledgenode",
    "audiotranscriptionnode",
    "tasknode",
    "agentnode",
    "agentnodetask",
    "edge",
    "startnode",
    "endnode",
    "subgraphnode",
    "decisiontablenode",
    "classificationdecisiontablenode",
    "webhooktriggernode",
    "telegramtriggernode",
    "scheduletriggernode",
    "graphnote",
]
MISSING_PK = 999_999_999

DELETE_ROUTES = [
    pytest.param("pythonnode-detail", PythonNode, _python_node, id="python-node"),
    pytest.param("edge-detail", Edge, _edge, id="edge"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("route, model, make_payload", CREATE_ROUTES)
@pytest.mark.parametrize(
    "flows_permissions, expected_status",
    [
        pytest.param(READ_CREATE, status.HTTP_403_FORBIDDEN, id="create-without-update"),
        pytest.param(READ_UPDATE, status.HTTP_201_CREATED, id="update"),
    ],
)
def test_adding_flow_content_needs_flows_update(
    custom_role_client,
    acme,
    acme_graph,
    route,
    model,
    make_payload,
    flows_permissions,
    expected_status,
):
    payload = make_payload(acme_graph)
    count_before = model.objects.filter(graph=acme_graph).count()
    client = custom_role_client(acme, {ResourceType.FLOWS: flows_permissions}, "flow-content")

    response = client.post(reverse(route), payload, format="json")

    assert response.status_code == expected_status, response.content
    created = 1 if expected_status == status.HTTP_201_CREATED else 0
    assert model.objects.filter(graph=acme_graph).count() == count_before + created


@pytest.mark.django_db
@pytest.mark.parametrize("route, model, make_row", DELETE_ROUTES)
@pytest.mark.parametrize(
    "flows_permissions, expected_status",
    [
        pytest.param(READ_DELETE, status.HTTP_403_FORBIDDEN, id="delete-without-update"),
        pytest.param(READ_UPDATE, status.HTTP_204_NO_CONTENT, id="update"),
    ],
)
def test_removing_flow_content_needs_flows_update(
    custom_role_client,
    acme,
    acme_graph,
    route,
    model,
    make_row,
    flows_permissions,
    expected_status,
):
    row = make_row(acme_graph)
    client = custom_role_client(acme, {ResourceType.FLOWS: flows_permissions}, "flow-content")

    response = client.delete(reverse(route, args=[row.id]))

    assert response.status_code == expected_status, response.content
    still_there = expected_status == status.HTTP_403_FORBIDDEN
    assert model.objects.filter(pk=row.id).exists() == still_there


# The gate runs before validation and the object lookup, so an empty body and a
# missing pk are enough: without the gate they would be a 400 and a 404.
@pytest.mark.django_db
@pytest.mark.parametrize("basename", FLOW_CONTENT_BASENAMES)
def test_every_flow_content_create_is_gated_by_flows_update(
    custom_role_client, acme, basename
):
    # USE, so the trigger node viewsets' own USE check cannot be what refuses.
    client = custom_role_client(
        acme, {ResourceType.FLOWS: READ_CREATE | Permission.USE}, "sweep-create"
    )

    response = client.post(reverse(f"{basename}-list"), {}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content


@pytest.mark.django_db
@pytest.mark.parametrize("basename", FLOW_CONTENT_BASENAMES)
def test_every_flow_content_delete_is_gated_by_flows_update(
    custom_role_client, acme, basename
):
    client = custom_role_client(acme, {ResourceType.FLOWS: READ_DELETE}, "sweep-delete")

    response = client.delete(reverse(f"{basename}-detail", args=[MISSING_PK]))

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
