"""
Tests verifying that GraphBulkSaveService.save() returns a (Graph, temp_id_map)
tuple and that the REST save_flow endpoint still returns 200.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import ConditionalEdge, Edge, PythonNode
from tables.serializers.graph_bulk_save_serializers import GraphBulkSaveInputSerializer
from tables.services.graph_bulk_save_service import GraphBulkSaveService
from tests.fixtures import *  # noqa: F401,F403


_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


# ---------------------------------------------------------------------------
# GraphBulkSaveService.save() returns (graph, temp_id_map)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_returns_tuple_graph_and_temp_id_map(graph):
    """save() must return a two-tuple (Graph, dict)."""
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {"graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    result = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    assert isinstance(result, tuple), "save() must return a tuple"
    assert len(result) == 2, "save() must return exactly 2 elements"
    saved_graph, temp_id_map = result
    assert saved_graph is graph  # same object, mutated in place
    assert isinstance(temp_id_map, dict)


@pytest.mark.django_db
def test_save_temp_id_map_empty_when_no_new_nodes(graph, python_node):
    """When only updates and no new nodes are in the payload, temp_id_map is empty."""
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": python_node.id,
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
                "node_name": "updated",
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    _, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    assert temp_id_map == {}


@pytest.mark.django_db
def test_save_temp_id_map_contains_new_node_mapping(graph):
    """When a new node is created with a temp_id, temp_id_map holds the mapping."""
    temp_id = "ccccdddd-0000-0000-0000-000000000001"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    _, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    assert temp_id in temp_id_map
    real_id = temp_id_map[temp_id]
    assert isinstance(real_id, int)
    # Verify the DB node actually has this id.
    assert PythonNode.objects.filter(id=real_id, graph=graph).exists()


@pytest.mark.django_db
def test_save_temp_id_map_multiple_new_nodes(graph):
    """Multiple new nodes produce one entry per temp_id in the map."""
    temp_id_1 = "ccccdddd-0000-0000-0000-000000000002"
    temp_id_2 = "ccccdddd-0000-0000-0000-000000000003"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "temp_id": temp_id_1,
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
                "node_name": "node_a",
            },
            {
                "temp_id": temp_id_2,
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
                "node_name": "node_b",
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    _, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    assert temp_id_1 in temp_id_map
    assert temp_id_2 in temp_id_map
    assert temp_id_map[temp_id_1] != temp_id_map[temp_id_2]


# ---------------------------------------------------------------------------
# REST endpoint still returns 200
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rest_save_flow_still_returns_200(auth_client, graph):
    """The save_flow REST endpoint must return 200 after the save() signature change."""
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {"graph": graph.id, "python_code": _PYTHON_CODE_DATA},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_rest_save_flow_with_temp_id_returns_200(auth_client, graph):
    """REST save_flow with temp_id node returns 200 (temp_id_map is silently ignored)."""
    temp_id = "ccccdddd-0000-0000-0000-000000000004"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "temp_id": temp_id,
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content
    assert PythonNode.objects.filter(graph=graph).count() == 1


# ---------------------------------------------------------------------------
# graph_collab regression: edges must also register their own temp_id -> real id
# mapping, so a subsequent flush of the same (now id-stamped) edge routes to
# UPDATE instead of re-creating a duplicate row.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_temp_id_map_contains_new_edge_mapping(graph, python_node, crew_node):
    """A newly-created edge with its own temp_id registers that temp_id in the map."""
    edge_temp_id = "aaaabbbb-0000-0000-0000-000000000001"
    payload = {
        "save_version": graph.save_version,
        "edge_list": [
            {
                "temp_id": edge_temp_id,
                "graph": graph.id,
                "start_node_id": python_node.id,
                "end_node_id": crew_node.id,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    _, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    assert edge_temp_id in temp_id_map
    real_edge_id = temp_id_map[edge_temp_id]
    assert isinstance(real_edge_id, int)
    assert Edge.objects.filter(
        id=real_edge_id, graph=graph, start_node_id=python_node.id
    ).exists()


@pytest.mark.django_db
def test_save_edge_temp_id_and_endpoint_temp_id_in_same_request(graph, crew_node):
    """An edge's own temp_id and its endpoint's temp_id both resolve in one flush."""
    node_temp_id = "aaaabbbb-0000-0000-0000-000000000002"
    edge_temp_id = "aaaabbbb-0000-0000-0000-000000000003"
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "temp_id": node_temp_id,
                "graph": graph.id,
                "python_code": _PYTHON_CODE_DATA,
            },
        ],
        "edge_list": [
            {
                "temp_id": edge_temp_id,
                "graph": graph.id,
                "start_temp_id": node_temp_id,
                "end_node_id": crew_node.id,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    _, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    assert node_temp_id in temp_id_map
    assert edge_temp_id in temp_id_map
    new_node = PythonNode.objects.get(graph=graph)
    real_edge_id = temp_id_map[edge_temp_id]
    assert Edge.objects.filter(
        id=real_edge_id,
        graph=graph,
        start_node_id=new_node.id,
        end_node_id=crew_node.id,
    ).exists()


@pytest.mark.django_db
def test_save_second_flush_of_stamped_edge_updates_not_duplicates(
    graph, python_node, crew_node
):
    """Reproduces the graph_collab regression: once an edge's own temp_id is
    remapped to a real ``id`` (as GraphLiveStateService.apply_id_remap now
    does), a second flush carrying that ``id`` must route to UPDATE, not a
    second INSERT that violates the unique_graph_edge constraint."""

    edge_temp_id = "aaaabbbb-0000-0000-0000-000000000004"
    create_payload = {
        "save_version": graph.save_version,
        "edge_list": [
            {
                "temp_id": edge_temp_id,
                "graph": graph.id,
                "start_node_id": python_node.id,
                "end_node_id": crew_node.id,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=create_payload)
    assert serializer.is_valid(), serializer.errors
    graph, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )
    graph.refresh_from_db(fields=["save_version"])
    real_edge_id = temp_id_map[edge_temp_id]
    assert Edge.objects.filter(graph=graph).count() == 1

    # Second flush: the snapshot now carries the stamped real "id" instead of
    # "temp_id" — exactly what apply_id_remap produces.
    update_payload = {
        "save_version": graph.save_version,
        "edge_list": [
            {
                "id": real_edge_id,
                "graph": graph.id,
                "start_node_id": python_node.id,
                "end_node_id": crew_node.id,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=update_payload)
    assert serializer.is_valid(), serializer.errors

    GraphBulkSaveService().save(graph, serializer.validated_data, org_id=graph.org_id)

    assert Edge.objects.filter(graph=graph).count() == 1
    assert Edge.objects.filter(id=real_edge_id).exists()


@pytest.mark.django_db
def test_save_temp_id_map_contains_new_conditional_edge_mapping(
    graph, python_code, crew_node
):
    """A newly-created conditional edge with its own temp_id registers that
    temp_id in the map."""
    cond_edge_temp_id = "aaaabbbb-0000-0000-0000-000000000005"
    payload = {
        "save_version": graph.save_version,
        "conditional_edge_list": [
            {
                "temp_id": cond_edge_temp_id,
                "graph": graph.id,
                "source_node_id": crew_node.id,
                "input_map": {},
                "python_code": _PYTHON_CODE_DATA,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=payload)
    assert serializer.is_valid(), serializer.errors

    _, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )

    assert cond_edge_temp_id in temp_id_map
    real_id = temp_id_map[cond_edge_temp_id]
    assert isinstance(real_id, int)
    assert ConditionalEdge.objects.filter(
        id=real_id, graph=graph, source_node_id=crew_node.id
    ).exists()


@pytest.mark.django_db
def test_save_second_flush_of_stamped_conditional_edge_updates_not_duplicates(
    graph, crew_node
):
    """Same EST-3020 regression, for conditional_edge_list."""
    cond_edge_temp_id = "aaaabbbb-0000-0000-0000-000000000006"
    create_payload = {
        "save_version": graph.save_version,
        "conditional_edge_list": [
            {
                "temp_id": cond_edge_temp_id,
                "graph": graph.id,
                "source_node_id": crew_node.id,
                "input_map": {},
                "python_code": _PYTHON_CODE_DATA,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=create_payload)
    assert serializer.is_valid(), serializer.errors
    graph, temp_id_map = GraphBulkSaveService().save(
        graph, serializer.validated_data, org_id=graph.org_id
    )
    graph.refresh_from_db(fields=["save_version"])
    real_id = temp_id_map[cond_edge_temp_id]
    assert ConditionalEdge.objects.filter(graph=graph).count() == 1

    update_payload = {
        "save_version": graph.save_version,
        "conditional_edge_list": [
            {
                "id": real_id,
                "graph": graph.id,
                "source_node_id": crew_node.id,
                "input_map": {},
                "python_code": _PYTHON_CODE_DATA,
            },
        ],
    }
    serializer = GraphBulkSaveInputSerializer(data=update_payload)
    assert serializer.is_valid(), serializer.errors

    GraphBulkSaveService().save(graph, serializer.validated_data, org_id=graph.org_id)

    assert ConditionalEdge.objects.filter(graph=graph).count() == 1
    assert ConditionalEdge.objects.filter(id=real_id).exists()
