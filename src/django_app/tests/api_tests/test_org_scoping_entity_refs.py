"""Cross-org reference leaks in entity write bodies (QA: 'Organization ignored
when editing some entity fields'). Each test drives an org_a client that tries
to reference an org_b resource and expects a 400 rejection."""

import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.graph_models import (
    AgentNode,
    Condition,
    ConditionalEdge,
    ConditionGroup,
    DecisionTableNode,
    StartNode,
)
from tables.models.label_models import Label
from tables.models.python_models import PythonCode
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _admin_client(django_user_model, org, email):
    # Org Admin: full CRUD on workspace resources, so writes aren't blocked by
    # the verb gate and we isolate the org-reference checks under test.
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_a(db, django_user_model, org_a):
    return _admin_client(django_user_model, org_a, "admin_a@example.com")


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


# ---- A: graph label_ids ----


@pytest.mark.django_db
def test_graph_label_ids_cross_org_rejected(client_a, org_a, org_b):
    other_label = Label.objects.create(name="b-label", org=org_b)
    resp = client_a.post(
        "/api/graphs/", {"name": "g1", "label_ids": [other_label.id]}, format="json"
    )
    assert resp.status_code == 400
    assert "label_ids" in str(resp.data)


@pytest.mark.django_db
def test_graph_label_ids_accepts_flow_scope_label(client_a, org_a):
    flow_label = Label.objects.create(name="flow-label", org=org_a, scope=Label.Scope.FLOW)
    resp = client_a.post(
        "/api/graphs/", {"name": "g1", "label_ids": [flow_label.id]}, format="json"
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["label_ids"] == [flow_label.id]


@pytest.mark.django_db
def test_graph_label_ids_rejects_tool_scope_label(client_a, org_a):
    tool_label = Label.objects.create(name="tool-label", org=org_a, scope=Label.Scope.TOOL)
    resp = client_a.post(
        "/api/graphs/", {"name": "g1", "label_ids": [tool_label.id]}, format="json"
    )
    assert resp.status_code == 400
    assert "label_ids" in str(resp.data)


# ---- B: graph FK repoint on a node (update) ----


@pytest.mark.django_db
def test_agent_node_graph_repoint_cross_org_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    node = AgentNode.objects.create(graph=graph_a, node_name="n1")
    resp = client_a.patch(
        f"/api/agentnodes/{node.id}/", {"graph": graph_b.id}, format="json"
    )
    assert resp.status_code == 400
    assert "graph" in str(resp.data)


# ---- C: edge start/end node refs (same-graph) ----


@pytest.mark.django_db
def test_edge_cross_org_graph_rejected(client_a, org_a, org_b):
    graph_b = _graph(org_b, "b")
    start = StartNode.objects.create(graph=graph_b, variables={})
    resp = client_a.post(
        "/api/edges/",
        {"graph": graph_b.id, "start_node_id": start.id, "end_node_id": start.id},
        format="json",
    )
    assert resp.status_code == 400
    assert "graph" in str(resp.data)


@pytest.mark.django_db
def test_edge_node_from_other_graph_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    start_a = StartNode.objects.create(graph=graph_a, variables={})
    foreign = StartNode.objects.create(graph=graph_b, variables={})
    resp = client_a.post(
        "/api/edges/",
        {
            "graph": graph_a.id,
            "start_node_id": start_a.id,
            "end_node_id": foreign.id,  # belongs to another graph/org
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "end_node_id" in str(resp.data)


_CONDITIONAL_EDGE_CODE = {"code": "def main(): return True", "entrypoint": "main", "libraries": []}


@pytest.mark.django_db
def test_conditional_edge_source_node_from_other_graph_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    foreign = StartNode.objects.create(graph=_graph(org_b, "b"), variables={})
    resp = client_a.post(
        "/api/conditionaledges/",
        {
            "graph": graph_a.id,
            "source_node_id": foreign.id,
            "python_code": _CONDITIONAL_EDGE_CODE,
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "source_node_id" in str(resp.data)
    assert not ConditionalEdge.objects.filter(graph=graph_a).exists()


@pytest.mark.django_db
def test_conditional_edge_source_node_same_graph_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    start_a = StartNode.objects.create(graph=graph_a, variables={})
    resp = client_a.post(
        "/api/conditionaledges/",
        {
            "graph": graph_a.id,
            "source_node_id": start_a.id,
            "python_code": _CONDITIONAL_EDGE_CODE,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data


@pytest.mark.django_db
def test_conditional_edge_source_node_patch_cross_graph_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    start_a = StartNode.objects.create(graph=graph_a, variables={})
    foreign = StartNode.objects.create(graph=_graph(org_b, "b"), variables={})
    edge = ConditionalEdge.objects.create(
        graph=graph_a,
        source_node_id=start_a.id,
        python_code=PythonCode.objects.create(code="def main(): return True"),
    )
    resp = client_a.patch(
        f"/api/conditionaledges/{edge.id}/",
        {"source_node_id": foreign.id},
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "source_node_id" in str(resp.data)
    edge.refresh_from_db()
    assert edge.source_node_id == start_a.id


# ---- C: decision-table next-node refs (same-graph) ----


@pytest.mark.django_db
def test_decision_table_next_node_cross_graph_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    foreign = StartNode.objects.create(graph=graph_b, variables={})
    resp = client_a.post(
        "/api/decision-table-node/",
        {
            "graph": graph_a.id,
            "node_name": "dt1",
            "default_next_node_id": foreign.id,  # node in another graph/org
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "default_next_node_id" in str(resp.data)


@pytest.mark.django_db
def test_decision_table_condition_group_next_node_cross_graph_rejected(
    client_a, org_a, org_b
):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    foreign = StartNode.objects.create(graph=graph_b, variables={})
    resp = client_a.post(
        "/api/decision-table-node/",
        {
            "graph": graph_a.id,
            "node_name": "dt1",
            "condition_groups": [
                {
                    "group_name": "grp1",
                    "group_type": "simple",
                    "next_node_id": foreign.id,  # node in another graph/org
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "next_node_id" in str(resp.data)
    # No leak: the rejected request must not have created the node.
    assert not DecisionTableNode.objects.filter(node_name="dt1").exists()


@pytest.mark.django_db
def test_decision_table_condition_group_next_node_patch_cross_graph_rejected(
    client_a, org_a, org_b
):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    foreign = StartNode.objects.create(graph=graph_b, variables={})
    dt = DecisionTableNode.objects.create(graph=graph_a, node_name="dt1")
    resp = client_a.patch(
        f"/api/decision-table-node/{dt.id}/",
        {
            "condition_groups": [
                {
                    "group_name": "grp1",
                    "group_type": "simple",
                    "next_node_id": foreign.id,  # node in another graph/org
                }
            ]
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "next_node_id" in str(resp.data)
    # No leak: the rejected patch must not have created the cross-org group.
    assert not ConditionGroup.objects.filter(decision_table_node=dt).exists()


def _foreign_decision_table_group(org):
    foreign_node = DecisionTableNode.objects.create(graph=_graph(org, "b"), node_name="dt_b")
    foreign_group = ConditionGroup.objects.create(
        decision_table_node=foreign_node, group_name="grp_b", group_type="simple"
    )
    Condition.objects.create(
        condition_group=foreign_group, condition_name="cond_b", condition="False"
    )
    return foreign_group


def _write_decision_table(client, method, graph, condition_groups):
    if method == "post":
        return client.post(
            "/api/decision-table-node/",
            {"graph": graph.id, "node_name": "dt1", "condition_groups": condition_groups},
            format="json",
        )
    node = DecisionTableNode.objects.create(graph=graph, node_name="dt1")
    return client.patch(
        f"/api/decision-table-node/{node.id}/",
        {"condition_groups": condition_groups},
        format="json",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(("method", "expected_status"), [("post", 201), ("patch", 200)])
def test_decision_table_group_parent_id_cross_org_ignored(
    client_a, org_a, org_b, method, expected_status
):
    graph_a = _graph(org_a, "a")
    foreign_node = _foreign_decision_table_group(org_b).decision_table_node
    resp = _write_decision_table(
        client_a,
        method,
        graph_a,
        [
            {
                "group_name": "injected",
                "group_type": "simple",
                "expression": "True",
                "decision_table_node_id": foreign_node.id,  # node in another org
            }
        ],
    )
    assert resp.status_code == expected_status, resp.data
    assert list(foreign_node.condition_groups.values_list("group_name", flat=True)) == ["grp_b"]
    injected = ConditionGroup.objects.get(group_name="injected")
    assert injected.decision_table_node.graph_id == graph_a.id


@pytest.mark.django_db
@pytest.mark.parametrize(("method", "expected_status"), [("post", 201), ("patch", 200)])
def test_decision_table_condition_parent_id_cross_org_ignored(
    client_a, org_a, org_b, method, expected_status
):
    graph_a = _graph(org_a, "a")
    foreign_group = _foreign_decision_table_group(org_b)
    resp = _write_decision_table(
        client_a,
        method,
        graph_a,
        [
            {
                "group_name": "grp1",
                "group_type": "complex",
                "conditions": [
                    {
                        "condition_name": "injected",
                        "condition": "True",
                        "condition_group_id": foreign_group.id,  # group in another org
                    }
                ],
            }
        ],
    )
    assert resp.status_code == expected_status, resp.data
    assert list(foreign_group.conditions.values_list("condition_name", flat=True)) == ["cond_b"]
    injected = Condition.objects.get(condition_name="injected")
    assert injected.condition_group.decision_table_node.graph_id == graph_a.id


@pytest.mark.django_db
def test_decision_table_condition_group_next_node_same_graph_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    target = StartNode.objects.create(graph=graph_a, variables={})
    resp = client_a.post(
        "/api/decision-table-node/",
        {
            "graph": graph_a.id,
            "node_name": "dt1",
            "condition_groups": [
                {
                    "group_name": "grp1",
                    "group_type": "simple",
                    "next_node_id": target.id,  # node in the same graph
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data

    # Cross-org and same-org init-realtime coverage lives in
    # tests/api_tests/init_realtime_agent_definition_test.py, which exercises
    # the agent_definition_id path (the only path init-realtime accepts).
