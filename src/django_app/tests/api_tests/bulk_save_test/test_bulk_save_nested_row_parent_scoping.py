"""Bulk save builds decision table condition groups and conditions, and classification
decision table condition groups, from the raw nested request dicts. A client must not
be able to steer those rows to another parent through a foreign-key attname
(``decision_table_node_id``, ``condition_group_id``,
``classification_decision_table_node_id``, ``prompt_id``, ``section_id``) pointing into
another organization's flow.

Each test sends such an id and checks that nothing appears under the foreign parent, that
the foreign parent's rows are untouched, and that the saved row belongs to the node in
the request. Each case runs both for a node created by the request and for an update of
an existing node of the request's own graph.

Because those rows are built from an allow-list of input columns, a column added to one
of the models is silently dropped until it is added to the list: the drift guards below
fail first. The round trip checks that every column the frontend sends still persists.
"""

import uuid

import pytest
from django.urls import reverse
from rest_framework import status
from tables.constants.decision_table_constants import (
    CONDITION_GROUP_INPUT_FIELDS,
    CONDITION_INPUT_FIELDS,
)
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationConditionGroupSection,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    Condition,
    ConditionGroup,
    DecisionTableNode,
    Graph,
)
from tables.services.classification_decision_table_node_children import (
    CLASSIFICATION_CONDITION_GROUP_INPUT_FIELDS,
)

from tests.fixtures import *

_NODE_STATES = ["new_node", "existing_node"]


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _post_save(client, graph: Graph, **lists):
    payload = {"save_version": graph.save_version, **lists}
    return client.post(_save_url(graph.id), payload, format="json")


def _node_payload(graph: Graph, node_state: str, existing_node, condition_groups: list) -> dict:
    if node_state == "existing_node":
        return {
            "id": existing_node.id,
            "graph": graph.id,
            "node_name": existing_node.node_name,
            "condition_groups": condition_groups,
        }
    return {"graph": graph.id, "node_name": "attacker_node", "condition_groups": condition_groups}


def _saved_node(model, graph: Graph, node_state: str, existing_node):
    if node_state == "existing_node":
        return existing_node
    return model.objects.get(graph=graph, node_name="attacker_node")


@pytest.fixture
def other_org_graph(other_org) -> Graph:
    return Graph.objects.create(name="other_org_graph", org=other_org)


@pytest.fixture
def foreign_decision_table_node(other_org_graph) -> DecisionTableNode:
    node = DecisionTableNode.objects.create(graph=other_org_graph, node_name="victim_dt")
    group = ConditionGroup.objects.create(
        decision_table_node=node, group_name="victim_group", group_type="simple", order=0
    )
    Condition.objects.create(
        condition_group=group, condition_name="victim_condition", order=0, condition="False"
    )
    return node


@pytest.fixture
def foreign_condition_group(foreign_decision_table_node) -> ConditionGroup:
    return foreign_decision_table_node.condition_groups.get()


@pytest.fixture
def own_decision_table_node(graph) -> DecisionTableNode:
    node = DecisionTableNode.objects.create(graph=graph, node_name="own_dt")
    ConditionGroup.objects.create(
        decision_table_node=node, group_name="own_group", group_type="simple", order=0
    )
    return node


@pytest.fixture
def foreign_cdt_node(other_org_graph) -> ClassificationDecisionTableNode:
    node = ClassificationDecisionTableNode.objects.create(
        graph=other_org_graph, node_name="victim_cdt"
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=node, group_name="victim_group", order=0
    )
    return node


@pytest.fixture
def foreign_prompt(foreign_cdt_node) -> ClassificationDecisionTablePrompt:
    return ClassificationDecisionTablePrompt.objects.create(
        cdt_node=foreign_cdt_node, prompt_key="victim_prompt", prompt_text="other org secret"
    )


@pytest.fixture
def foreign_section(foreign_cdt_node) -> ClassificationConditionGroupSection:
    return ClassificationConditionGroupSection.objects.create(
        id=uuid.uuid4(), classification_decision_table_node=foreign_cdt_node, name="victim"
    )


@pytest.fixture
def own_cdt_node(graph) -> ClassificationDecisionTableNode:
    node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="own_cdt")
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=node,
        group_name="own_group",
        order=0,
        route_code="own_route",
    )
    return node


def _injected_cdt_group(**foreign_ref) -> dict:
    return {
        "group_name": "injected",
        "order": 1,
        "expression": "True",
        "manipulation": "print('injected')",
        **foreign_ref,
    }


# ---- Decision table ----


@pytest.mark.django_db
@pytest.mark.parametrize("node_state", _NODE_STATES)
def test_dt_group_decision_table_node_id_cannot_target_other_org_node(
    auth_client, graph, own_decision_table_node, foreign_decision_table_node, node_state
):
    group = {
        "group_name": "injected",
        "group_type": "simple",
        "order": 0,
        "expression": "True",
        "manipulation": "print('injected')",
        "decision_table_node_id": foreign_decision_table_node.id,
    }

    response = _post_save(
        auth_client,
        graph,
        decision_table_node_list=[
            _node_payload(graph, node_state, own_decision_table_node, [group])
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert list(
        foreign_decision_table_node.condition_groups.values_list("group_name", flat=True)
    ) == ["victim_group"]
    injected = ConditionGroup.objects.get(group_name="injected")
    node = _saved_node(DecisionTableNode, graph, node_state, own_decision_table_node)
    assert injected.decision_table_node_id == node.id


@pytest.mark.django_db
@pytest.mark.parametrize("node_state", _NODE_STATES)
def test_dt_condition_condition_group_id_cannot_target_other_org_group(
    auth_client, graph, own_decision_table_node, foreign_condition_group, node_state
):
    group = {
        "group_name": "own_carrier",
        "group_type": "complex",
        "order": 0,
        "conditions": [
            {
                "condition_name": "injected",
                "order": 0,
                "condition": "True",
                "condition_group_id": foreign_condition_group.id,
            }
        ],
    }

    response = _post_save(
        auth_client,
        graph,
        decision_table_node_list=[
            _node_payload(graph, node_state, own_decision_table_node, [group])
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert list(foreign_condition_group.conditions.values_list("condition_name", flat=True)) == [
        "victim_condition"
    ]
    injected = Condition.objects.get(condition_name="injected")
    node = _saved_node(DecisionTableNode, graph, node_state, own_decision_table_node)
    assert injected.condition_group.decision_table_node_id == node.id
    assert injected.condition_group.group_name == "own_carrier"


# ---- Classification decision table ----


@pytest.mark.django_db
@pytest.mark.parametrize("node_state", _NODE_STATES)
def test_cdt_group_node_id_cannot_target_other_org_node(
    auth_client, graph, own_cdt_node, foreign_cdt_node, node_state
):
    group = _injected_cdt_group(classification_decision_table_node_id=foreign_cdt_node.id)

    response = _post_save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            _node_payload(graph, node_state, own_cdt_node, [group])
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert list(foreign_cdt_node.condition_groups.values_list("group_name", flat=True)) == [
        "victim_group"
    ]
    injected = ClassificationConditionGroup.objects.get(group_name="injected")
    node = _saved_node(ClassificationDecisionTableNode, graph, node_state, own_cdt_node)
    assert injected.classification_decision_table_node_id == node.id


@pytest.mark.django_db
@pytest.mark.parametrize("node_state", _NODE_STATES)
def test_cdt_group_prompt_id_cannot_attach_other_org_prompt(
    auth_client, graph, own_cdt_node, foreign_prompt, node_state
):
    group = _injected_cdt_group(prompt_id=foreign_prompt.id)

    response = _post_save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            _node_payload(graph, node_state, own_cdt_node, [group])
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not foreign_prompt.condition_groups.exists()
    injected = ClassificationConditionGroup.objects.get(group_name="injected")
    node = _saved_node(ClassificationDecisionTableNode, graph, node_state, own_cdt_node)
    assert injected.classification_decision_table_node_id == node.id
    assert injected.prompt_id is None


@pytest.mark.django_db
def test_cdt_existing_group_update_prompt_id_cannot_attach_other_org_prompt(
    auth_client, graph, own_cdt_node, foreign_prompt
):
    existing_group = own_cdt_node.condition_groups.get()
    group = {
        "group_name": existing_group.group_name,
        "order": 0,
        "route_code": existing_group.route_code,
        "prompt_id": foreign_prompt.id,
    }

    response = _post_save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            _node_payload(graph, "existing_node", own_cdt_node, [group])
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not foreign_prompt.condition_groups.exists()
    existing_group.refresh_from_db()
    assert existing_group.classification_decision_table_node_id == own_cdt_node.id
    assert existing_group.prompt_id is None


@pytest.mark.django_db
@pytest.mark.parametrize("node_state", _NODE_STATES)
def test_cdt_group_section_id_cannot_attach_other_org_section(
    auth_client, graph, own_cdt_node, foreign_section, node_state
):
    group = _injected_cdt_group(section_id=str(foreign_section.id))

    response = _post_save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            _node_payload(graph, node_state, own_cdt_node, [group])
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not foreign_section.condition_groups.exists()
    injected = ClassificationConditionGroup.objects.get(group_name="injected")
    node = _saved_node(ClassificationDecisionTableNode, graph, node_state, own_cdt_node)
    assert injected.classification_decision_table_node_id == node.id
    assert injected.section_id is None


# ---- Allow-list drift guards ----

_SOFT_DELETE_COLUMNS = {"is_soft_deleted", "soft_deleted_at"}


@pytest.mark.parametrize(
    ("model", "server_owned", "input_fields"),
    [
        (
            ConditionGroup,
            {"id", "decision_table_node", *_SOFT_DELETE_COLUMNS},
            CONDITION_GROUP_INPUT_FIELDS,
        ),
        (
            Condition,
            {"id", "condition_group", *_SOFT_DELETE_COLUMNS},
            CONDITION_INPUT_FIELDS,
        ),
        (
            ClassificationConditionGroup,
            {
                "id",
                "classification_decision_table_node",
                "prompt",
                "section",
                "created_at",
                "updated_at",
                *_SOFT_DELETE_COLUMNS,
            },
            CLASSIFICATION_CONDITION_GROUP_INPUT_FIELDS,
        ),
    ],
    ids=["ConditionGroup", "Condition", "ClassificationConditionGroup"],
)
def test_input_allow_list_covers_every_client_column(model, server_owned, input_fields):
    columns = {field.name for field in model._meta.concrete_fields}

    assert server_owned <= columns
    assert columns - server_owned == input_fields


# ---- Classification decision table round trip ----


def _frontend_cdt_group(next_node_id: int, *, route_code: str | None, suffix: str) -> dict:
    """Mirror the condition group shape the flow editor's save payload sends."""
    return {
        "group_name": f"group_{route_code or 'unrouted'}",
        "order": 1 if route_code else 2,
        "expression": f"x == {suffix!r}",
        "prompt_key": None,
        "prompt": None,
        "manipulation": f"y = {suffix!r}",
        "continue_flag": suffix == "updated",
        "route_code": route_code,
        "section": None,
        "next_node_id": next_node_id,
        "dock_visible": suffix != "updated",
        "field_expressions": {"field": f'== "{suffix}"'},
        "field_manipulations": {"field": suffix},
    }


_ROUND_TRIP_COLUMNS = (
    "order",
    "expression",
    "manipulation",
    "continue_flag",
    "route_code",
    "next_node_id",
    "dock_visible",
    "field_expressions",
    "field_manipulations",
)


def _assert_groups_persisted(node, sent_groups: list[dict]) -> None:
    saved = {group.group_name: group for group in node.condition_groups.all()}
    assert set(saved) == {group["group_name"] for group in sent_groups}
    for sent in sent_groups:
        group = saved[sent["group_name"]]
        for column in _ROUND_TRIP_COLUMNS:
            assert getattr(group, column) == sent[column], column


@pytest.mark.django_db
def test_cdt_frontend_group_columns_persist_on_create_and_update(
    auth_client, graph, start_node, python_node
):
    first_target, second_target = start_node, python_node
    created_groups = [
        _frontend_cdt_group(first_target.id, route_code="route_a", suffix="created"),
        _frontend_cdt_group(first_target.id, route_code=None, suffix="created"),
    ]

    create_response = _post_save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            {"graph": graph.id, "node_name": "round_trip", "condition_groups": created_groups}
        ],
    )

    assert create_response.status_code == status.HTTP_200_OK, create_response.content
    node = ClassificationDecisionTableNode.objects.get(graph=graph, node_name="round_trip")
    _assert_groups_persisted(node, created_groups)
    group_ids = set(node.condition_groups.values_list("id", flat=True))

    graph.refresh_from_db()
    updated_groups = [
        _frontend_cdt_group(second_target.id, route_code="route_a", suffix="updated"),
        _frontend_cdt_group(second_target.id, route_code=None, suffix="updated"),
    ]
    update_response = _post_save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "round_trip",
                "condition_groups": updated_groups,
            }
        ],
    )

    assert update_response.status_code == status.HTTP_200_OK, update_response.content
    _assert_groups_persisted(node, updated_groups)
    assert set(node.condition_groups.values_list("id", flat=True)) == group_ids
