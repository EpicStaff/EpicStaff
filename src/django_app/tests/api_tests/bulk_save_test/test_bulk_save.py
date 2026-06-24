import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import (
    Condition,
    ConditionGroup,
    CrewNode,
    DecisionTableNode,
    Edge,
    Graph,
    PythonNode,
)
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


# PythonNodeSerializer.python_code is a nested serializer — always pass a dict.
_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


# ---------------------------------------------------------------------------
# PythonNode — create / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_python_node(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {"graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert PythonNode.objects.filter(graph=graph).count() == 1


@pytest.mark.django_db
def test_create_python_node_with_temp_id(auth_client, graph):
    temp_id = "aaaabbbb-0000-0000-0000-000000000001"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
                "temp_id": temp_id,
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert PythonNode.objects.filter(graph=graph).count() == 1


@pytest.mark.django_db
def test_update_python_node(auth_client, graph, python_node):
    new_name = "updated_python_node"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": python_node.id,
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
                "node_name": new_name,
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    python_node.refresh_from_db()
    assert python_node.node_name == new_name


@pytest.mark.django_db
def test_delete_python_node(auth_client, graph, python_node):
    payload = {
        "save_version": graph.save_version,
        "deleted": {"python_node_ids": [python_node.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not PythonNode.objects.filter(id=python_node.id).exists()


@pytest.mark.django_db
def test_create_python_node_missing_code_field(auth_client, graph):
    """python_code dict with missing required 'code' field → 400."""
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {"graph": graph.id, "python_code": {"entrypoint": "main"}},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "python_node_list" in response.data["errors"]


# ---------------------------------------------------------------------------
# CrewNode — create / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_crew_node(auth_client, graph, crew):
    # CrewNodeSerializer uses crew_id (write-only IntegerField), not crew.
    payload = {
        "save_version": graph.save_version,
        "crew_node_list": [
            {"graph": graph.id, "crew_id": crew.id},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert CrewNode.objects.filter(graph=graph).count() == 1


@pytest.mark.django_db
def test_update_crew_node(auth_client, graph, crew, crew_node):
    new_name = "updated_crew_node"
    payload = {
        "save_version": graph.save_version,
        "crew_node_list": [
            {
                "id": crew_node.id,
                "graph": graph.id,
                "crew_id": crew.id,
                "node_name": new_name,
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    crew_node.refresh_from_db()
    assert crew_node.node_name == new_name


@pytest.mark.django_db
def test_delete_crew_node(auth_client, graph, crew_node):
    payload = {
        "save_version": graph.save_version,
        "deleted": {"crew_node_ids": [crew_node.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not CrewNode.objects.filter(id=crew_node.id).exists()


# ---------------------------------------------------------------------------
# DecisionTableNode — create / update / delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_decision_table_node(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "decision_table_node_list": [
            {"graph": graph.id, "node_name": "dt_node_new"},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert DecisionTableNode.objects.filter(graph=graph).count() == 1


@pytest.mark.django_db
def test_create_decision_table_node_with_condition_groups(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_with_groups",
                "condition_groups": [
                    {
                        "group_name": "group_a",
                        "group_type": "simple",
                        "order": 0,
                        "conditions": [
                            {
                                "condition_name": "cond_1",
                                "condition": "x > 0",
                                "order": 0,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    node = DecisionTableNode.objects.get(graph=graph, node_name="dt_with_groups")
    assert ConditionGroup.objects.filter(decision_table_node=node).count() == 1
    group = ConditionGroup.objects.get(decision_table_node=node)
    assert Condition.objects.filter(condition_group=group).count() == 1


@pytest.mark.django_db
def test_update_decision_table_node_replaces_condition_groups(
    auth_client, graph, decision_table_node
):
    old_group = ConditionGroup.objects.create(
        decision_table_node=decision_table_node,
        group_name="old_group",
        group_type="simple",
        order=0,
    )

    payload = {
        "save_version": graph.save_version,
        "decision_table_node_list": [
            {
                "id": decision_table_node.id,
                "graph": graph.id,
                "node_name": "dt_node_1",
                "condition_groups": [
                    {
                        "group_name": "new_group",
                        "group_type": "complex",
                        "order": 0,
                    }
                ],
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not ConditionGroup.objects.filter(id=old_group.id).exists()
    assert ConditionGroup.objects.filter(
        decision_table_node=decision_table_node, group_name="new_group"
    ).exists()


@pytest.mark.django_db
def test_delete_decision_table_node(auth_client, graph, decision_table_node):
    payload = {
        "save_version": graph.save_version,
        "deleted": {"decision_table_node_ids": [decision_table_node.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not DecisionTableNode.objects.filter(id=decision_table_node.id).exists()


# ---------------------------------------------------------------------------
# Edge — create / delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_edge_with_real_node_ids(auth_client, graph, python_node, crew_node):
    payload = {
        "save_version": graph.save_version,
        "edge_list": [
            {
                "graph": graph.id,
                "start_node_id": python_node.id,
                "end_node_id": crew_node.id,
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert Edge.objects.filter(
        graph=graph, start_node_id=python_node.id, end_node_id=crew_node.id
    ).exists()


@pytest.mark.django_db
def test_create_edge_with_temp_id(auth_client, graph, crew_node):
    """New PythonNode created in same request; edge references it via temp_id."""
    temp_id = "cccc0000-0000-0000-0000-000000000002"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
                "temp_id": temp_id,
            },
        ],
        "edge_list": [
            {
                "graph": graph.id,
                "start_temp_id": temp_id,
                "end_node_id": crew_node.id,
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    new_node = PythonNode.objects.get(graph=graph)
    assert Edge.objects.filter(
        graph=graph, start_node_id=new_node.id, end_node_id=crew_node.id
    ).exists()


@pytest.mark.django_db
def test_delete_edge(auth_client, graph, edge):
    payload = {
        "save_version": graph.save_version,
        "deleted": {"edge_ids": [edge.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not Edge.objects.filter(id=edge.id).exists()


# ---------------------------------------------------------------------------
# Combined multi-operation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_update_delete_in_one_request(
    auth_client, graph, crew, python_node, crew_node
):
    """Create a new PythonNode, update crew_node name, delete python_node — all atomically."""
    new_name = "crew_node_renamed"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {"graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
        "crew_node_list": [
            {
                "id": crew_node.id,
                "graph": graph.id,
                "crew_id": crew.id,
                "node_name": new_name,
            }
        ],
        "deleted": {"python_node_ids": [python_node.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not PythonNode.objects.filter(id=python_node.id).exists()
    assert PythonNode.objects.filter(graph=graph).count() == 1  # only the newly created
    crew_node.refresh_from_db()
    assert crew_node.node_name == new_name


@pytest.mark.django_db
def test_edge_with_temp_id_and_new_node_same_request(auth_client, graph, crew_node):
    """Create PythonNode with temp_id and an edge using that temp_id in one request."""
    temp_id = "dddd0000-0000-0000-0000-000000000003"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
                "temp_id": temp_id,
            }
        ],
        "edge_list": [
            {
                "graph": graph.id,
                "start_temp_id": temp_id,
                "end_node_id": crew_node.id,
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    new_node = PythonNode.objects.get(graph=graph)
    assert Edge.objects.filter(
        graph=graph, start_node_id=new_node.id, end_node_id=crew_node.id
    ).exists()


# ---------------------------------------------------------------------------
# Validation / error cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_node_id_in_payload(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {"id": 99999, "graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "python_node_list" in response.data["errors"]


@pytest.mark.django_db
def test_delete_node_from_different_graph(auth_client, graph, python_code):
    other_graph = Graph.objects.create(name="other_graph")
    other_node = PythonNode.objects.create(graph=other_graph, python_code=python_code)

    payload = {
        "save_version": graph.save_version,
        "deleted": {"python_node_ids": [other_node.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "errors" in response.data


@pytest.mark.django_db
def test_edge_both_node_id_and_temp_id_provided(
    auth_client, graph, python_node, crew_node
):
    payload = {
        "save_version": graph.save_version,
        "edge_list": [
            {
                "graph": graph.id,
                "start_node_id": python_node.id,
                "start_temp_id": "eeee0000-0000-0000-0000-000000000004",
                "end_node_id": crew_node.id,
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "errors" in response.data


@pytest.mark.django_db
def test_edge_unknown_temp_id(auth_client, graph, crew_node):
    payload = {
        "save_version": graph.save_version,
        "edge_list": [
            {
                "graph": graph.id,
                "start_temp_id": "ffff0000-0000-0000-0000-000000000005",
                "end_node_id": crew_node.id,
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "errors" in response.data


@pytest.mark.django_db
def test_graph_not_found(auth_client):
    response = auth_client.post(_save_url(99999), {"save_version": 1}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_empty_payload(auth_client, graph):
    payload = {"save_version": graph.save_version}
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content


# ---------------------------------------------------------------------------
# Optimistic locking — save_flow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_flow_success_increments_save_version(auth_client, graph):
    """Correct save_version → 200, response save_version is bumped by 1."""
    initial_version = graph.save_version
    payload = {
        "save_version": initial_version,
        "python_node_list": [
            {"graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["save_version"] == initial_version + 1
    graph.refresh_from_db()
    assert graph.save_version == initial_version + 1


@pytest.mark.django_db
def test_save_flow_stale_version_returns_409(auth_client, graph):
    """Stale save_version → 409 with current_version in body."""
    # Advance the DB version ahead of the client's expectation
    Graph.objects.filter(pk=graph.pk).update(save_version=5)

    payload = {
        "save_version": 1,  # stale
        "python_node_list": [
            {"graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_409_CONFLICT, response.content


@pytest.mark.django_db
def test_save_flow_conflict_rolls_back_bulk_save(auth_client, graph):
    """Stale version → no nodes are persisted from the request payload."""
    Graph.objects.filter(pk=graph.pk).update(save_version=99)

    payload = {
        "save_version": 1,  # stale
        "python_node_list": [
            {"graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    assert PythonNode.objects.filter(graph=graph).count() == 0
