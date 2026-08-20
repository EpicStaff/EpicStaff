"""Cross-org reference leaks in entity write bodies (QA: 'Organization ignored
when editing some entity fields'). Each test drives an org_a client that tries
to reference an org_b resource and expects a 400 rejection."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tables.models import Agent, Crew, Graph
from tables.models.graph_models import (
    ConditionGroup,
    CrewNode,
    DecisionTableNode,
    Edge,
    StartNode,
)
from tables.models.label_models import Label
from tables.models.llm_models import LLMConfig
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


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


# ---- A1: crew planning_llm_config ----


@pytest.mark.django_db
def test_crew_planning_llm_config_cross_org_rejected(client_a, org_a, org_b):
    other = LLMConfig.objects.create(custom_name="b-cfg", org=org_b)
    resp = client_a.post(
        "/api/crews/", {"name": "c1", "planning_llm_config": other.id}, format="json"
    )
    assert resp.status_code == 400
    assert "planning_llm_config" in str(resp.data)


@pytest.mark.django_db
def test_crew_planning_llm_config_same_org_ok(client_a, org_a):
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    resp = client_a.post(
        "/api/crews/", {"name": "c1", "planning_llm_config": mine.id}, format="json"
    )
    assert resp.status_code == 201, resp.data


# ---- A2: graph label_ids ----


@pytest.mark.django_db
def test_graph_label_ids_cross_org_rejected(client_a, org_a, org_b):
    other_label = Label.objects.create(name="b-label", org=org_b)
    resp = client_a.post(
        "/api/graphs/", {"name": "g1", "label_ids": [other_label.id]}, format="json"
    )
    assert resp.status_code == 400
    assert "label_ids" in str(resp.data)


# ---- B: graph FK repoint on a node (update) ----


@pytest.mark.django_db
def test_crew_node_graph_repoint_cross_org_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    crew = Crew.objects.create(name="crew", org=org_a)
    node = CrewNode.objects.create(crew=crew, graph=graph_a, node_name="n1")
    resp = client_a.patch(
        f"/api/crewnodes/{node.id}/", {"graph": graph_b.id}, format="json"
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


# ---- C: init-realtime agent ----


@pytest.mark.django_db
def test_init_realtime_cross_org_agent_rejected(client_a, org_a, org_b):
    other_agent = Agent.objects.create(role="r", goal="g", backstory="b", org=org_b)
    resp = client_a.post(
        "/api/init-realtime/", {"agent_id": other_agent.id}, format="json"
    )
    assert resp.status_code == 400
    assert "agent_id" in str(resp.data)


@pytest.mark.django_db
def test_init_realtime_same_org_agent_allowed(client_a, org_a):
    agent = Agent.objects.create(role="r", goal="g", backstory="b", org=org_a)
    with patch(
        "tables.views.views.realtime_service.init_realtime", return_value="conn-1"
    ) as init:
        resp = client_a.post(
            "/api/init-realtime/", {"agent_id": agent.id}, format="json"
        )
    assert resp.status_code == 201, resp.data
    assert resp.data["connection_key"] == "conn-1"
    # The active org must reach the service: it is what binds decryption to the
    # org the caller was authorized for.
    assert init.call_args.kwargs["org_id"] == org_a.id
