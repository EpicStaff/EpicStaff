"""Node and edge ids in a partial-export job request are caller input.

They must be resolved inside the caller's organisation. An id owned by another
organisation has to look exactly like an id that does not exist, and must not
pull that node's dependencies into the archive.
"""

import json

import pytest
from rest_framework import status

from tables.import_export.enums import EntityType
from tables.models import Graph, TransferJob
from tables.models.graph_models import DecisionTableNode, Edge, PythonNode
from tables.models.python_models import PythonCode

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.transfer_job_helpers import FinishedExport, export_via_job

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


def _export(client, graph, payload) -> FinishedExport:
    return export_via_job(client, f"/api/graphs/{graph.id}/partial-export-jobs/", payload)


def _failed_as_not_found(exported: FinishedExport, message: str) -> bool:
    return (
        exported.job.status == TransferJob.Status.FAILED
        and exported.job.error == {"code": "not_found", "message": message}
        and exported.members == {}
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("list_key", "make_node"),
    [
        ("python_node_list", _python_node),
        ("decision_table_node_list", _decision_table_node),
    ],
)
def test_foreign_node_id_looks_like_a_missing_one(
    client, own_graph, foreign_graph, list_key, make_node
):
    foreign_node = make_node(foreign_graph)

    foreign = _export(client, own_graph, {list_key: [foreign_node.id]})
    missing = _export(client, own_graph, {list_key: [NONEXISTENT_ID]})

    assert _failed_as_not_found(foreign, f"Node with id={foreign_node.id} not found.")
    assert _failed_as_not_found(missing, f"Node with id={NONEXISTENT_ID} not found.")


@pytest.mark.django_db
def test_foreign_id_next_to_own_ids_exports_nothing(client, own_graph, foreign_graph):
    own_node = _python_node(own_graph, code="# own code")
    foreign_node = _python_node(foreign_graph, code=f"# {FOREIGN_CODE_MARKER}")

    exported = _export(client, own_graph, {"python_node_list": [own_node.id, foreign_node.id]})

    assert _failed_as_not_found(exported, f"Node with id={foreign_node.id} not found.")
    assert FOREIGN_CODE_MARKER not in json.dumps(exported.job.error)


@pytest.mark.django_db
def test_foreign_edge_id_looks_like_a_missing_one(client, own_graph, foreign_graph):
    own_node = _python_node(own_graph)
    foreign_start, foreign_end = _python_node(foreign_graph), _python_node(foreign_graph)
    foreign_edge = Edge.objects.create(
        graph=foreign_graph, start_node_id=foreign_start.id, end_node_id=foreign_end.id
    )

    foreign = _export(
        client, own_graph, {"python_node_list": [own_node.id], "edge_list": [foreign_edge.id]}
    )
    missing = _export(
        client, own_graph, {"python_node_list": [own_node.id], "edge_list": [NONEXISTENT_ID]}
    )

    assert _failed_as_not_found(foreign, f"Edge with id={foreign_edge.id} not found.")
    assert _failed_as_not_found(missing, f"Edge with id={NONEXISTENT_ID} not found.")


@pytest.mark.django_db
def test_nodes_of_another_orgs_flow_cannot_be_exported_at_all(client, foreign_graph):
    foreign_node = _python_node(foreign_graph, code=f"# {FOREIGN_CODE_MARKER}")

    response = client.post(
        f"/api/graphs/{foreign_graph.id}/partial-export-jobs/",
        {"python_node_list": [foreign_node.id]},
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not TransferJob.objects.exists()


@pytest.mark.django_db
def test_own_nodes_and_edges_still_export_with_their_dependencies(client, own_graph):
    start, end = _python_node(own_graph, code="# start"), _python_node(own_graph, code="# end")
    edge = Edge.objects.create(graph=own_graph, start_node_id=start.id, end_node_id=end.id)

    exported = _export(
        client, own_graph, {"python_node_list": [start.id, end.id], "edge_list": [edge.id]}
    )

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert exported.job.main_entity == TransferJob.MainEntity.FLOW_NODES
    assert exported.job.display_name == "2 nodes from acme-flow"
    assert exported.job.file_name.startswith("graph_nodes_nodes_acme_flow_")
    assert set(exported.members) == {"export.json"}
    envelope = exported.envelope
    assert {node["id"] for node in envelope[EntityType.PYTHON_NODE]} == {start.id, end.id}
    assert [exported_edge["id"] for exported_edge in envelope["edge_list"]] == [edge.id]
    assert "# start" in exported.members["export.json"].decode()
    assert "# end" in exported.members["export.json"].decode()
