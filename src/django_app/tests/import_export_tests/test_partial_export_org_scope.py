"""EST-4267: node and edge ids in a partial-export request are caller input.

They must be resolved inside the caller's organisation. An id owned by another
organisation has to look exactly like an id that does not exist, and must not
pull that node's dependencies into the download.
"""

import json

import pytest
from rest_framework import status

from tables.import_export.enums import EntityType
from tables.models import Graph
from tables.models.graph_models import DecisionTableNode, Edge, PythonNode
from tables.models.python_models import PythonCode

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

FOREIGN_CODE_MARKER = "BETA_SECRET_SOURCE_MARKER"
NONEXISTENT_ID = 987654


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.fixture
def own_graph(acme):
    return Graph.objects.create(name="acme-flow", org=acme)


@pytest.fixture
def foreign_graph(beta):
    return Graph.objects.create(name="beta-flow", org=beta)


def _python_node(graph, code="def main(): pass"):
    return PythonNode.objects.create(
        graph=graph, python_code=PythonCode.objects.create(code=code), node_name="py"
    )


def _decision_table_node(graph):
    return DecisionTableNode.objects.create(graph=graph, node_name="dt")


def _post(client, graph, payload):
    return client.post(f"/api/graphs/{graph.id}/partial-export/", payload, format="json")


def _node_not_found(entity_type, node_id):
    return {
        "errors": [
            {
                "node_id": node_id,
                "entity_type": entity_type,
                "error": f"Node with id={node_id} not found.",
            }
        ]
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("list_key", "entity_type", "make_node"),
    [
        ("python_node_list", EntityType.PYTHON_NODE, _python_node),
        ("decision_table_node_list", EntityType.DECISION_TABLE_NODE, _decision_table_node),
    ],
)
def test_foreign_node_id_looks_like_a_missing_one(
    client, own_graph, foreign_graph, list_key, entity_type, make_node
):
    foreign_node = make_node(foreign_graph)

    foreign = _post(client, own_graph, {list_key: [foreign_node.id]})
    missing = _post(client, own_graph, {list_key: [NONEXISTENT_ID]})

    assert foreign.status_code == missing.status_code == status.HTTP_400_BAD_REQUEST
    assert foreign.json() == _node_not_found(entity_type, foreign_node.id)
    assert missing.json() == _node_not_found(entity_type, NONEXISTENT_ID)


@pytest.mark.django_db
def test_foreign_node_dependencies_are_not_exported(client, own_graph, foreign_graph):
    foreign_node = _python_node(foreign_graph, code=f"# {FOREIGN_CODE_MARKER}")

    response = _post(client, own_graph, {"python_node_list": [foreign_node.id]})

    assert FOREIGN_CODE_MARKER not in response.content.decode()


@pytest.mark.django_db
def test_foreign_id_next_to_own_ids_exports_nothing(client, own_graph, foreign_graph):
    own_node = _python_node(own_graph, code="# own code")
    foreign_node = _python_node(foreign_graph, code=f"# {FOREIGN_CODE_MARKER}")

    response = _post(client, own_graph, {"python_node_list": [own_node.id, foreign_node.id]})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == _node_not_found(EntityType.PYTHON_NODE, foreign_node.id)
    assert FOREIGN_CODE_MARKER not in response.content.decode()


@pytest.mark.django_db
def test_foreign_edge_id_looks_like_a_missing_one(client, own_graph, foreign_graph):
    own_node = _python_node(own_graph)
    foreign_start, foreign_end = _python_node(foreign_graph), _python_node(foreign_graph)
    foreign_edge = Edge.objects.create(
        graph=foreign_graph, start_node_id=foreign_start.id, end_node_id=foreign_end.id
    )

    foreign = _post(
        client, own_graph, {"python_node_list": [own_node.id], "edge_list": [foreign_edge.id]}
    )
    missing = _post(
        client, own_graph, {"python_node_list": [own_node.id], "edge_list": [NONEXISTENT_ID]}
    )

    assert foreign.status_code == missing.status_code == status.HTTP_400_BAD_REQUEST
    assert foreign.json() == {
        "errors": [{"edge_id": foreign_edge.id, "error": f"Edge with id={foreign_edge.id} not found."}]
    }
    assert missing.json() == {
        "errors": [{"edge_id": NONEXISTENT_ID, "error": f"Edge with id={NONEXISTENT_ID} not found."}]
    }


@pytest.mark.django_db
def test_own_nodes_and_edges_still_export_with_their_dependencies(client, own_graph):
    start, end = _python_node(own_graph, code="# start"), _python_node(own_graph, code="# end")
    edge = Edge.objects.create(graph=own_graph, start_node_id=start.id, end_node_id=end.id)

    response = _post(
        client, own_graph, {"python_node_list": [start.id, end.id], "edge_list": [edge.id]}
    )

    assert response.status_code == status.HTTP_200_OK
    exported = json.loads(response.content)
    assert {node["id"] for node in exported[EntityType.PYTHON_NODE]} == {start.id, end.id}
    assert [exported_edge["id"] for exported_edge in exported["edge_list"]] == [edge.id]
    assert "# start" in response.content.decode()
    assert "# end" in response.content.decode()
