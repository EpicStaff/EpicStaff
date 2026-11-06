"""Which nodes a run of a flow reaches from its Start node, along every route crew takes."""

import pytest
from django.apps import apps
from django.db import models
from django.utils import timezone

from tables.models import Edge, Graph, StartNode
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ConditionGroup,
    DecisionTableNode,
    EndNode,
)
from tables.services.flow_reachability import nodes_reachable_from_start
from tests.fixtures import *


@pytest.fixture
def flow(default_org) -> Graph:
    return Graph.objects.create(name="Routing", org=default_org)


def _end_node(flow: Graph) -> EndNode:
    return EndNode.objects.create(graph=flow, output_map={})


def _decision_table(flow: Graph, node_number: int, **routes) -> DecisionTableNode:
    return DecisionTableNode.objects.create(
        graph=flow, node_name="Route", node_number=node_number, **routes
    )


def _classification_table(flow: Graph, node_number: int, **routes):
    return ClassificationDecisionTableNode.objects.create(
        graph=flow, node_name="Classify", node_number=node_number, **routes
    )


@pytest.mark.django_db
def test_flow_without_a_start_node_reaches_nothing(flow):
    _end_node(flow)

    assert nodes_reachable_from_start(flow.id) == set()


@pytest.mark.django_db
def test_edges_are_followed_and_a_loop_ends(flow):
    start = StartNode.objects.create(graph=flow, variables={})
    first = _decision_table(flow, 1)
    second = _decision_table(flow, 2)
    unconnected = _decision_table(flow, 3)
    Edge.objects.create(graph=flow, start_node_id=start.id, end_node_id=first.id)
    Edge.objects.create(graph=flow, start_node_id=first.id, end_node_id=second.id)
    Edge.objects.create(graph=flow, start_node_id=second.id, end_node_id=first.id)
    Edge.objects.create(graph=flow, start_node_id=unconnected.id, end_node_id=first.id)

    assert nodes_reachable_from_start(flow.id) == {start.id, first.id, second.id}


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["default_next_node_id", "next_error_node_id", "condition"])
def test_every_decision_table_route_is_followed(flow, route):
    start = StartNode.objects.create(graph=flow, variables={})
    end_node = _end_node(flow)
    table = _decision_table(
        flow, 1, **({} if route == "condition" else {route: end_node.id})
    )
    if route == "condition":
        ConditionGroup.objects.create(
            decision_table_node=table,
            group_name="High score",
            group_type="complex",
            expression="variables.score > 5",
            next_node_id=end_node.id,
        )
    Edge.objects.create(graph=flow, start_node_id=start.id, end_node_id=table.id)

    assert nodes_reachable_from_start(flow.id) == {start.id, table.id, end_node.id}


@pytest.mark.django_db
def test_a_condition_in_the_recycle_bin_is_not_a_route(flow):
    start = StartNode.objects.create(graph=flow, variables={})
    end_node = _end_node(flow)
    table = _decision_table(flow, 1)
    ConditionGroup.objects.create(
        decision_table_node=table,
        group_name="High score",
        group_type="complex",
        expression="variables.score > 5",
        next_node_id=end_node.id,
        active=False,
        soft_deleted_at=timezone.now(),
    )
    Edge.objects.create(graph=flow, start_node_id=start.id, end_node_id=table.id)

    assert nodes_reachable_from_start(flow.id) == {start.id, table.id}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route", "reaches_end"),
    [
        pytest.param("default_next_node_id", True, id="default-route"),
        pytest.param("next_error_node_id", True, id="error-route"),
        pytest.param("enabled_row", True, id="enabled-row"),
        pytest.param("disabled_row", False, id="disabled-row-never-runs"),
    ],
)
def test_classification_table_routes_are_followed_except_a_disabled_row(
    flow, route, reaches_end
):
    start = StartNode.objects.create(graph=flow, variables={})
    end_node = _end_node(flow)
    table = _classification_table(
        flow, 1, **({route: end_node.id} if route.endswith("_id") else {})
    )
    if route.endswith("_row"):
        ClassificationConditionGroup.objects.create(
            classification_decision_table_node=table,
            group_name="High score",
            next_node_id=end_node.id,
            dock_visible=route == "enabled_row",
        )
    Edge.objects.create(graph=flow, start_node_id=start.id, end_node_id=table.id)

    expected = {start.id, table.id} | ({end_node.id} if reaches_end else set())
    assert nodes_reachable_from_start(flow.id) == expected


# A route is stored as a plain integer holding a node's global id, not a foreign key,
# since it may point to a node of any type: an edge's ends, or a table's next node.
def _is_route_field(field) -> bool:
    return (
        not field.is_relation
        and isinstance(field, models.IntegerField)
        and field.attname.endswith("node_id")
    )


# The route fields the tests above show FlowRoutes following, by model label.
_ROUTE_FIELDS_FLOW_ROUTES_FOLLOWS = {
    "tables.Edge.start_node_id",
    "tables.Edge.end_node_id",
    "tables.DecisionTableNode.default_next_node_id",
    "tables.DecisionTableNode.next_error_node_id",
    "tables.ConditionGroup.next_node_id",
    "tables.ClassificationDecisionTableNode.default_next_node_id",
    "tables.ClassificationDecisionTableNode.next_error_node_id",
    "tables.ClassificationConditionGroup.next_node_id",
}


def test_every_route_field_of_a_model_is_one_flow_routes_follows():
    route_fields = {
        f"{model._meta.label}.{field.attname}"
        for model in apps.get_models()
        for field in model._meta.concrete_fields
        if _is_route_field(field)
    }

    assert route_fields == _ROUTE_FIELDS_FLOW_ROUTES_FOLLOWS, (
        "A route field was added or removed. Handle a new one in every place "
        "`next_error_node_id` is read: FlowRoutes.from_rows (and a test above), "
        "`edge_referenced_ids` in SessionManagerService._build_graph_data (name "
        "resolution), and crew's routing. A run leaves out every node behind a route "
        "FlowRoutes doesn't follow, and crew fails when the run takes that route."
    )
