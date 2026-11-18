import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from agents.models import AgentDefinition
from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.models.surface_models import Surface
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph
from tables.models.graph_models import AgentNode, TaskNode

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


def _bin(row):
    """Soft-delete one row without cascading, so each test isolates one filter."""
    type(row).all_objects.filter(pk=row.pk).update(active=False, soft_deleted_at=timezone.now())


def _url(surface):
    return f"/api/surfaces/{surface.pk}/usage/"


def _usage(client, org, surface):
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.get(_url(surface))


@pytest.fixture
def surface(acme):
    return Surface.objects.create(name="shared", org=acme)


@pytest.fixture
def admin_client(client_as, admin_acme):
    return client_as(admin_acme)


def _agent(org, name):
    return AgentDefinition.objects.create(name=name, org=org)


def test_explicit_default_rows_listed_per_place_sorted(admin_client, acme, surface):
    zed, alpha = _agent(acme, "Zed"), _agent(acme, "Alpha")
    AgentDefaultSurface.objects.create(agent_definition=zed, surface=surface, place=SurfacePlace.ALL)
    AgentDefaultSurface.objects.create(agent_definition=alpha, surface=surface, place=SurfacePlace.FLOW)
    AgentDefaultSurface.objects.create(agent_definition=alpha, surface=surface, place=SurfacePlace.CHAT)

    resp = _usage(admin_client, acme, surface)

    assert resp.status_code == 200
    assert resp.data["agents"] == [
        {"id": alpha.id, "name": "Alpha", "place": "chat"},
        {"id": alpha.id, "name": "Alpha", "place": "flow"},
        {"id": zed.id, "name": "Zed", "place": "all"},
    ]
    assert resp.data["hidden_agent_count"] == 0
    assert resp.data["flows"] == []
    assert resp.data["hidden_flow_count"] == 0


def test_owner_agent_is_an_implicit_all_row(admin_client, acme):
    owner = _agent(acme, "Owner")
    owned = Surface.objects.create(name="owned", org=acme, owner_agent=owner)

    resp = _usage(admin_client, acme, owned)

    assert resp.data["agents"] == [{"id": owner.id, "name": "Owner", "place": "all"}]


def test_owner_with_explicit_row_is_not_duplicated(admin_client, acme):
    owner = _agent(acme, "Owner")
    owned = Surface.objects.create(name="owned", org=acme, owner_agent=owner)
    AgentDefaultSurface.objects.create(agent_definition=owner, surface=owned, place=SurfacePlace.CHAT)

    resp = _usage(admin_client, acme, owned)

    assert resp.data["agents"] == [{"id": owner.id, "name": "Owner", "place": "chat"}]


def test_task_and_agent_nodes_are_grouped_under_one_graph(admin_client, acme, surface):
    researcher = _agent(acme, "Researcher")
    graph = Graph.objects.create(name="My flow", org=acme)
    task_node = TaskNode.objects.create(graph=graph, node_name="Summarize", agent_definition=researcher)
    agent_node = AgentNode.objects.create(graph=graph, node_name="Alpha node")
    task_node.surface_list.add(surface)
    agent_node.surface_list.add(surface)
    other_graph = Graph.objects.create(name="Another", org=acme)
    TaskNode.objects.create(graph=other_graph, node_name="Not attached")

    resp = _usage(admin_client, acme, surface)

    assert resp.data["flows"] == [
        {
            "id": graph.id,
            "name": "My flow",
            "nodes": [
                {
                    "id": agent_node.id,
                    "node_name": "Alpha node",
                    "node_type": "agent",
                    "agent_id": None,
                    "agent_name": None,
                },
                {
                    "id": task_node.id,
                    "node_name": "Summarize",
                    "node_type": "task",
                    "agent_id": researcher.id,
                    "agent_name": "Researcher",
                },
            ],
        }
    ]


def test_agent_default_surface_is_not_flow_usage(admin_client, acme, surface):
    agent = _agent(acme, "Agent")
    AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface, place=SurfacePlace.FLOW)
    TaskNode.objects.create(graph=Graph.objects.create(name="g", org=acme), node_name="n", agent_definition=agent)

    assert _usage(admin_client, acme, surface).data["flows"] == []


def test_soft_deleted_rows_are_excluded(admin_client, acme, surface):
    live_agent, dead_agent = _agent(acme, "Live"), _agent(acme, "Dead")
    AgentDefaultSurface.objects.create(agent_definition=live_agent, surface=surface, place=SurfacePlace.ALL)
    AgentDefaultSurface.objects.create(agent_definition=dead_agent, surface=surface, place=SurfacePlace.ALL)
    dead_row = AgentDefaultSurface.objects.create(
        agent_definition=live_agent, surface=surface, place=SurfacePlace.CHAT
    )
    _bin(dead_agent)
    _bin(dead_row)

    live_graph, dead_graph = Graph.objects.create(name="live", org=acme), Graph.objects.create(name="dead", org=acme)
    live_node = TaskNode.objects.create(graph=live_graph, node_name="live node", agent_definition=dead_agent)
    dead_node = TaskNode.objects.create(graph=live_graph, node_name="dead node")
    node_in_dead_graph = AgentNode.objects.create(graph=dead_graph, node_name="in dead graph")
    for node in (live_node, dead_node, node_in_dead_graph):
        node.surface_list.add(surface)
    _bin(dead_node)
    _bin(dead_graph)

    resp = _usage(admin_client, acme, surface)

    assert resp.data["agents"] == [{"id": live_agent.id, "name": "Live", "place": "all"}]
    assert [flow["id"] for flow in resp.data["flows"]] == [live_graph.id]
    # The deleted agent is shown as no agent rather than leaking its name.
    assert resp.data["flows"][0]["nodes"] == [
        {
            "id": live_node.id,
            "node_name": "live node",
            "node_type": "task",
            "agent_id": None,
            "agent_name": None,
        }
    ]


def test_deleted_owner_agent_is_not_listed(admin_client, acme):
    owner = _agent(acme, "Owner")
    owned = Surface.objects.create(name="owned", org=acme, owner_agent=owner)
    _bin(owner)

    assert _usage(admin_client, acme, owned).data["agents"] == []


def test_surface_of_another_org_is_404(admin_client, acme, beta):
    foreign = Surface.objects.create(name="foreign", org=beta)

    assert _usage(admin_client, acme, foreign).status_code == 404
    assert _usage(admin_client, acme, Surface(pk=2**31 - 1)).status_code == 404


def test_nodes_of_another_org_graph_are_not_listed(admin_client, acme, beta, surface):
    foreign_graph = Graph.objects.create(name="foreign", org=beta)
    TaskNode.objects.create(graph=foreign_graph, node_name="n").surface_list.add(surface)

    assert _usage(admin_client, acme, surface).data["flows"] == []


def _seed_usage(org, surface):
    agent = _agent(org, "Researcher")
    AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface, place=SurfacePlace.ALL)
    AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface, place=SurfacePlace.CHAT)
    graph = Graph.objects.create(name="flow", org=org)
    node = TaskNode.objects.create(graph=graph, node_name="n", agent_definition=agent)
    node.surface_list.add(surface)
    other = AgentNode.objects.create(graph=Graph.objects.create(name="other", org=org), node_name="m")
    other.surface_list.add(surface)
    return node


def test_without_flows_read_flows_are_only_counted(client_as, custom_role_user, acme, surface):
    _seed_usage(acme, surface)
    user = custom_role_user(
        acme,
        "no-flows@example.com",
        {ResourceType.SURFACES: Permission.READ, ResourceType.AGENTS: Permission.READ},
    )

    resp = _usage(client_as(user), acme, surface)

    assert resp.status_code == 200
    assert resp.data["flows"] == []
    assert resp.data["hidden_flow_count"] == 2
    assert len(resp.data["agents"]) == 2
    assert resp.data["hidden_agent_count"] == 0


def test_without_agents_read_agents_are_only_counted_and_node_agents_nulled(
    client_as, custom_role_user, acme, surface
):
    node = _seed_usage(acme, surface)
    user = custom_role_user(
        acme,
        "no-agents@example.com",
        {ResourceType.SURFACES: Permission.READ, ResourceType.FLOWS: Permission.READ},
    )

    resp = _usage(client_as(user), acme, surface)

    assert resp.status_code == 200
    assert resp.data["agents"] == []
    # One agent defaulting the surface in two places is still one hidden agent.
    assert resp.data["hidden_agent_count"] == 1
    assert resp.data["hidden_flow_count"] == 0
    flow = next(flow for flow in resp.data["flows"] if flow["id"] == node.graph_id)
    assert flow["nodes"][0]["agent_id"] is None
    assert flow["nodes"][0]["agent_name"] is None
    assert flow["nodes"][0]["node_name"] == "n"
    assert "Researcher" not in resp.content.decode()


def test_without_agents_read_owner_agent_is_only_counted(client_as, custom_role_user, acme):
    owned = Surface.objects.create(name="owned", org=acme, owner_agent=_agent(acme, "Secret Owner"))
    user = custom_role_user(
        acme,
        "no-agents-owner@example.com",
        {ResourceType.SURFACES: Permission.READ, ResourceType.FLOWS: Permission.READ},
    )

    resp = _usage(client_as(user), acme, owned)

    assert resp.status_code == 200
    assert resp.data["agents"] == []
    assert resp.data["hidden_agent_count"] == 1
    assert "Secret Owner" not in resp.content.decode()


def test_query_count_does_not_grow_with_rows(admin_client, acme, surface):
    _seed_usage(acme, surface)
    admin_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    with CaptureQueriesContext(connection) as small:
        admin_client.get(_url(surface))

    for index in range(5):
        agent = _agent(acme, f"Extra {index}")
        AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface, place=SurfacePlace.FLOW)
        graph = Graph.objects.create(name=f"g{index}", org=acme)
        TaskNode.objects.create(graph=graph, node_name="t", agent_definition=agent).surface_list.add(surface)
        AgentNode.objects.create(graph=graph, node_name="a", agent_definition=agent).surface_list.add(surface)
    with CaptureQueriesContext(connection) as large:
        admin_client.get(_url(surface))

    assert len(large) == len(small)
