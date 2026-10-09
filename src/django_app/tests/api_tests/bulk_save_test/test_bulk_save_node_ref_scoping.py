"""Bulk save must reject a real (non-temp) node reference that does not belong
to the graph being saved: edge endpoints, conditional edge sources and decision
table / classification decision table routing (default, error and each condition
group's next node). A node in another
organization's graph, a node in a sibling graph of the same organization, a
soft-deleted node and a nonexistent id are all rejected with the same response,
so existence never leaks. A rejected request writes nothing, so the graph's
save_version does not move.

The graph in the URL is the only graph a bulk save writes to: a per-item
``graph`` pointing elsewhere is overridden.

Same-graph happy paths for edges and decision table groups live in
test_bulk_save.py and test_bulk_save_decision_table.py.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ConditionalEdge,
    ConditionGroup,
    DecisionTableNode,
    Edge,
    Graph,
    StartNode,
)

from tests.fixtures import *  # noqa: F401,F403

_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}

_EDGE_REF_ERROR = "Edge references node IDs not found in this graph"
_ROUTING_REF_ERROR = "Decision table routing references node IDs not found in this graph"


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _post_save(client, graph: Graph, **lists):
    payload = {"save_version": graph.save_version, **lists}
    return client.post(_save_url(graph.id), payload, format="json")


def _edge_payload(graph: Graph, start_node_id: int, end_node_id: int) -> dict:
    return {
        "edge_list": [
            {"graph": graph.id, "start_node_id": start_node_id, "end_node_id": end_node_id}
        ]
    }


def _assert_save_version_unchanged(graph: Graph) -> None:
    version_before = graph.save_version
    graph.refresh_from_db()
    assert graph.save_version == version_before


@pytest.fixture
def other_org_node(other_org) -> StartNode:
    other_graph = Graph.objects.create(name="other_org_graph", org=other_org)
    return StartNode.objects.create(graph=other_graph, variables={})


@pytest.fixture
def sibling_graph(graph) -> Graph:
    return Graph.objects.create(name="sibling_graph", org=graph.org)


@pytest.fixture
def same_org_other_graph_node(sibling_graph) -> StartNode:
    return StartNode.objects.create(graph=sibling_graph, variables={})


@pytest.fixture
def nonexistent_node_id(graph) -> int:
    scratch_graph = Graph.objects.create(name="scratch_graph", org=graph.org)
    node = StartNode.objects.create(graph=scratch_graph, variables={})
    node_id = node.id
    node.delete()
    return node_id


@pytest.fixture
def soft_deleted_node(graph) -> StartNode:
    node = StartNode.objects.create(graph=graph, variables={})
    StartNode.all_objects.filter(pk=node.pk).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )
    return node


# (payload list key, node model, condition group model, extra condition group fields)
_ROUTING_TABLES = {
    "decision_table": (
        "decision_table_node_list",
        DecisionTableNode,
        ConditionGroup,
        {"group_type": "simple"},
    ),
    "classification_decision_table": (
        "classification_decision_table_node_list",
        ClassificationDecisionTableNode,
        ClassificationConditionGroup,
        {},
    ),
}

_FOREIGN_TARGETS = ["other_org_node", "same_org_other_graph_node"]


@pytest.mark.django_db
@pytest.mark.parametrize("target_fixture", _FOREIGN_TARGETS)
@pytest.mark.parametrize("table", list(_ROUTING_TABLES))
def test_group_next_node_outside_graph_rejected(request, auth_client, graph, table, target_fixture):
    list_key, node_model, group_model, group_extra = _ROUTING_TABLES[table]
    target = request.getfixturevalue(target_fixture)

    response = _post_save(
        auth_client,
        graph,
        **{
            list_key: [
                {
                    "graph": graph.id,
                    "node_name": "foreign_route",
                    "condition_groups": [
                        {
                            "group_name": "group",
                            "order": 0,
                            "next_node_id": target.id,
                            **group_extra,
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"]["edge_list"] == [f"{_ROUTING_REF_ERROR}: [{target.id}]"]
    assert not node_model.objects.filter(graph=graph).exists()
    assert not group_model.objects.filter(next_node_id=target.id).exists()
    _assert_save_version_unchanged(graph)


@pytest.mark.django_db
@pytest.mark.parametrize("target_fixture", _FOREIGN_TARGETS)
@pytest.mark.parametrize("field", ["default_next_node_id", "next_error_node_id"])
@pytest.mark.parametrize("table", list(_ROUTING_TABLES))
def test_node_routing_outside_graph_rejected(
    request, auth_client, graph, table, field, target_fixture
):
    # default/error refs stay in the node payload, so the node serializer's own
    # same-graph check rejects them (reported under the node list key) before
    # the batch check runs.
    list_key, node_model, _, _ = _ROUTING_TABLES[table]
    target = request.getfixturevalue(target_fixture)

    response = _post_save(
        auth_client,
        graph,
        **{list_key: [{"graph": graph.id, "node_name": "foreign_route", field: target.id}]},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert field in str(response.data["errors"][list_key])
    assert not node_model.objects.filter(graph=graph).exists()
    assert not node_model.all_objects.filter(**{field: target.id}).exists()
    _assert_save_version_unchanged(graph)


@pytest.mark.django_db
def test_cdt_group_next_node_in_same_graph_saved(auth_client, graph):
    target = StartNode.objects.create(graph=graph, variables={})

    response = _post_save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            {
                "graph": graph.id,
                "node_name": "cdt_local_route",
                "condition_groups": [
                    {"group_name": "group", "order": 0, "next_node_id": target.id}
                ],
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    group = ClassificationConditionGroup.objects.get(
        classification_decision_table_node__graph=graph
    )
    assert group.next_node_id == target.id


@pytest.mark.django_db
def test_edge_end_node_in_other_org_graph_rejected(auth_client, graph, start_node, other_org_node):
    response = _post_save(
        auth_client, graph, **_edge_payload(graph, start_node.id, other_org_node.id)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"]["edge_list"] == [f"{_EDGE_REF_ERROR}: [{other_org_node.id}]"]
    assert not Edge.objects.filter(graph=graph).exists()
    _assert_save_version_unchanged(graph)


@pytest.mark.django_db
def test_edge_start_node_in_same_org_other_graph_rejected(
    auth_client, graph, python_node, same_org_other_graph_node
):
    response = _post_save(
        auth_client, graph, **_edge_payload(graph, same_org_other_graph_node.id, python_node.id)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"]["edge_list"] == [
        f"{_EDGE_REF_ERROR}: [{same_org_other_graph_node.id}]"
    ]
    assert not Edge.objects.filter(graph=graph).exists()
    _assert_save_version_unchanged(graph)


@pytest.mark.django_db
def test_edge_end_node_soft_deleted_rejected(auth_client, graph, python_node, soft_deleted_node):
    response = _post_save(
        auth_client, graph, **_edge_payload(graph, python_node.id, soft_deleted_node.id)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"]["edge_list"] == [f"{_EDGE_REF_ERROR}: [{soft_deleted_node.id}]"]
    assert not Edge.objects.filter(graph=graph).exists()
    _assert_save_version_unchanged(graph)


@pytest.mark.django_db
def test_conditional_edge_source_node_in_other_org_graph_rejected(
    auth_client, graph, other_org_node
):
    response = _post_save(
        auth_client,
        graph,
        conditional_edge_list=[
            {
                "graph": graph.id,
                "source_node_id": other_org_node.id,
                "python_code": _PYTHON_CODE_DATA,
            }
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"]["edge_list"] == [f"{_EDGE_REF_ERROR}: [{other_org_node.id}]"]
    assert not ConditionalEdge.objects.filter(graph=graph).exists()
    _assert_save_version_unchanged(graph)


@pytest.mark.django_db
def test_conditional_edge_source_node_in_same_graph_saved(auth_client, graph, start_node):
    response = _post_save(
        auth_client,
        graph,
        conditional_edge_list=[
            {
                "graph": graph.id,
                "source_node_id": start_node.id,
                "python_code": _PYTHON_CODE_DATA,
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert ConditionalEdge.objects.filter(graph=graph, source_node_id=start_node.id).exists()


@pytest.mark.django_db
def test_foreign_node_id_response_matches_nonexistent_node_id(
    auth_client, graph, start_node, other_org_node, nonexistent_node_id
):
    foreign_response = _post_save(
        auth_client, graph, **_edge_payload(graph, start_node.id, other_org_node.id)
    )
    missing_response = _post_save(
        auth_client, graph, **_edge_payload(graph, start_node.id, nonexistent_node_id)
    )

    assert foreign_response.status_code == missing_response.status_code
    assert foreign_response.status_code == status.HTTP_400_BAD_REQUEST
    foreign_body = str(foreign_response.data).replace(str(other_org_node.id), "<id>")
    missing_body = str(missing_response.data).replace(str(nonexistent_node_id), "<id>")
    assert foreign_body == missing_body
    _assert_save_version_unchanged(graph)


@pytest.mark.django_db
def test_edge_item_graph_is_overridden_by_url_graph(
    auth_client, graph, start_node, python_node, sibling_graph
):
    response = _post_save(
        auth_client,
        graph,
        edge_list=[
            {
                "graph": sibling_graph.id,
                "start_node_id": start_node.id,
                "end_node_id": python_node.id,
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert Edge.objects.filter(
        graph=graph, start_node_id=start_node.id, end_node_id=python_node.id
    ).exists()
    assert not Edge.objects.filter(graph=sibling_graph).exists()


@pytest.mark.django_db
def test_node_update_item_graph_cannot_move_node_to_other_graph(
    auth_client, graph, start_node, sibling_graph
):
    response = _post_save(
        auth_client,
        graph,
        start_node_list=[
            {"id": start_node.id, "graph": sibling_graph.id, "variables": {}},
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    start_node.refresh_from_db()
    assert start_node.graph_id == graph.id
    assert not StartNode.objects.filter(graph=sibling_graph).exists()
