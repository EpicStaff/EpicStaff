"""TaskNode.surface_list (catalog Surface M2M) through /api/tasknodes/.

A task node may use shared surfaces of its org and surfaces owned by its own agent;
the same rules are re-checked when only the node's agent changes.
"""

from __future__ import annotations

import pytest

from agents.models import AgentDefinition, Surface
from tables.models.graph_models import Graph, TaskNode
from rbac.models import Organization


@pytest.fixture
def client(auth_client):
    """`auth_client` (conftest) is authenticated as a member of `default_org`
    and sends its id as the active-org header, so `org` below is aliased to
    `default_org` — the endpoints under test resolve the active org from that header."""
    return auth_client


@pytest.fixture
def org(default_org):
    return default_org


@pytest.fixture
def graph(db, org):
    return Graph.objects.create(name="task-node-surface-graph", org=org)


@pytest.fixture
def agents(db, org):
    return {
        name: AgentDefinition.objects.create(
            org=org, name=f"task-node-{name}", instruction_list=[{"name": "Instruction_1.md", "content": "do"}]
        )
        for name in ("agent", "agent_b")
    }


@pytest.fixture
def surfaces(db, org, agents):
    other_org = Organization.objects.create(name="other-org")
    return {
        "shared": Surface.objects.create(org=org, name="shared-a"),
        "shared_b": Surface.objects.create(org=org, name="shared-b"),
        "owned_by_agent": Surface.objects.create(org=org, name="owned-a", owner_agent=agents["agent"]),
        "owned_by_agent_b": Surface.objects.create(org=org, name="owned-b", owner_agent=agents["agent_b"]),
        "other_org": Surface.objects.create(org=other_org, name="foreign"),
    }


def _ids(surfaces, keys):
    return [surfaces[key].pk if key in surfaces else 999999 for key in keys]


def _stored(node):
    return set(node.surface_list.values_list("pk", flat=True))


@pytest.mark.parametrize(
    ("agent", "surface_keys", "status"),
    [
        (None, ["shared", "shared_b"], 201),
        (None, None, 201),
        (None, [], 201),
        ("agent", ["owned_by_agent"], 201),
        (None, ["other_org"], 400),
        ("agent", ["owned_by_agent_b"], 400),
        (None, ["owned_by_agent"], 400),
        (None, ["shared", "shared"], 400),
        (None, ["missing"], 400),
    ],
    ids=[
        "shared-surfaces", "no-surface-list", "empty-surface-list", "own-agents-surface",
        "another-orgs-surface", "another-agents-surface", "owned-surface-on-agentless-node",
        "same-surface-twice", "unknown-surface",
    ],
)
@pytest.mark.django_db
def test_create_accepts_only_surfaces_the_node_may_use(client, graph, agents, surfaces, agent, surface_keys, status):
    payload = {"graph": graph.pk, "node_name": "task"}
    if agent:
        payload["agent_definition"] = agents[agent].pk
    if surface_keys is not None:
        payload["surface_list"] = _ids(surfaces, surface_keys)

    response = client.post("/api/tasknodes/", payload, format="json")

    assert response.status_code == status, response.data
    if status == 201:
        expected = set(payload.get("surface_list", []))
        assert set(response.data["surface_list"]) == expected
        assert _stored(TaskNode.objects.get(pk=response.data["id"])) == expected
    else:
        assert "surface_list" in response.data["message"]
        assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.parametrize(
    ("agent", "attached", "patch", "status", "stored_after"),
    [
        (None, ["shared"], {"surface_list": ["shared_b"]}, 200, ["shared_b"]),
        (None, ["shared"], {"instructions": "updated"}, 200, ["shared"]),
        (None, ["shared"], {"surface_list": []}, 200, []),
        # Changing only the agent re-checks the surfaces already attached.
        ("agent", ["owned_by_agent"], {"agent_definition": "agent_b"}, 400, ["owned_by_agent"]),
        ("agent", ["owned_by_agent"], {"agent_definition": None}, 400, ["owned_by_agent"]),
        ("agent", ["shared"], {"agent_definition": "agent_b"}, 200, ["shared"]),
    ],
    ids=[
        "replace-set", "omitted-list-keeps-set", "empty-list-clears",
        "agent-change-strands-owned-surface", "agent-removed-strands-owned-surface", "agent-change-keeps-shared",
    ],
)
@pytest.mark.django_db
def test_update_replaces_keeps_or_rejects_the_surface_set(
    client, graph, agents, surfaces, agent, attached, patch, status, stored_after
):
    node = TaskNode.objects.create(graph=graph, node_name="task", agent_definition=agents.get(agent))
    node.surface_list.add(*(surfaces[key] for key in attached))
    payload = {
        key: _ids(surfaces, value) if key == "surface_list" else (agents[value].pk if key == "agent_definition" and value else value)
        for key, value in patch.items()
    }

    response = client.patch(f"/api/tasknodes/{node.pk}/", payload, format="json")

    assert response.status_code == status, response.data
    assert _stored(node) == set(_ids(surfaces, stored_after))


@pytest.mark.django_db
def test_content_hash_unchanged_by_surface_edit(graph, surfaces):
    """ContentHashMixin.generate_hash iterates _meta.fields only — M2M excluded."""
    node = TaskNode.objects.create(graph=graph, node_name="task-hash")
    hash_before = node.content_hash

    node.surface_list.add(surfaces["shared"])
    node.refresh_from_db()

    assert node.content_hash == hash_before
