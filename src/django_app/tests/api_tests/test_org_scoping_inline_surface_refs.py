"""Cross-org reference rejection for the nested `inline_surface` payload on
AgentNode/TaskNode (security regression tests, bug report follow-up).

A bug report claimed that `python_tools[].python_tool`, `mcp_tools[].mcp_tool`,
`knowledge[].collection`, and `storage_items[].storage_file` inside a node's
`inline_surface` payload all accept ids from another organization. In practice
each of those four fields is already org-scoped at the serializer layer
(`OrgVisiblePrimaryKeyRelatedField` / `OrgScopedPrimaryKeyRelatedField` in
`agents/serializers/surface_serializers.py`), so a cross-org pk is rejected
exactly like a non-existent pk before it ever reaches a validator. These tests
are regression guards proving that, for both the standalone node endpoints
(`/api/tasknodes/`, `/api/agentnodes/`) and the graph bulk-save endpoint
(`/graphs/{id}/save/`, which builds its own serializer context).

`python_tool` is a hybrid field (built-ins are intentionally shared across
orgs, only org-owned custom tools are scoped) — covered separately from the
strict fields (`mcp_tool`, `collection`, `storage_file`).
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from agents.models.surface_models import AgentInlineSurface, InlineSurface
from tables.models.graph_models import AgentNode, Graph, StorageFile, TaskNode
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def role_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Inline Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Inline Org B")


@pytest.fixture
def client_a(db, django_user_model, org_a, role_admin):
    user = django_user_model.objects.create_user(
        email="inline_admin_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_admin)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _rejected(resp):
    return resp.status_code == 400 and "does not exist" in str(resp.data)


def _python_tool(organization, *, built_in=False, name="py-tool"):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name=name,
        description="test",
        python_code=code,
        org=organization,
        built_in=built_in,
    )


def _mcp_tool(organization, *, name="mcp-tool", tool_name="mcp_tool_name"):
    return McpTool.objects.create(
        org=organization,
        name=name,
        transport="http://localhost/sse",
        tool_name=tool_name,
    )


def _collection(organization, *, name="collection"):
    return SourceCollection.objects.create(org=organization, collection_name=name)


def _storage_file(organization, *, path="a.txt"):
    return StorageFile.objects.create(org=organization, path=path, name=path)


# ---------------------------------------------------------------------------
# TaskNode: python_tools (hybrid — built-ins shared, custom tools org-scoped)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tasknode_create_rejects_cross_org_inline_python_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_tool = _python_tool(org_b, name="b-py-tool")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {
                "python_tools": [{"python_tool": b_tool.id, "mode": "allow"}]
            },
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_tasknode_create_allows_same_org_inline_python_tool(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_tool = _python_tool(org_a, name="a-py-tool")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {
                "python_tools": [{"python_tool": a_tool.id, "mode": "allow"}]
            },
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = TaskNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.python_tools.filter(python_tool_id=a_tool.id).exists()


@pytest.mark.django_db
def test_tasknode_create_allows_built_in_python_tool_from_another_org(
    client_a, org_a, org_b
):
    """Built-in tools are intentionally shared across every org — documenting
    that this is deliberate, not a leak."""
    graph = Graph.objects.create(name="a-graph", org=org_a)
    built_in_tool = _python_tool(org_b, built_in=True, name="shared-built-in")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {
                "python_tools": [{"python_tool": built_in_tool.id, "mode": "allow"}]
            },
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = TaskNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.python_tools.filter(
        python_tool_id=built_in_tool.id
    ).exists()


@pytest.mark.django_db
def test_tasknode_update_rejects_cross_org_inline_python_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = TaskNode.objects.create(graph=graph, node_name="ta")
    b_tool = _python_tool(org_b, name="b-py-tool-2")
    resp = client_a.patch(
        f"/api/tasknodes/{node.id}/",
        {
            "inline_surface": {
                "python_tools": [{"python_tool": b_tool.id, "mode": "allow"}]
            }
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not InlineSurface.objects.filter(task_node_id=node.id).exists()


# ---------------------------------------------------------------------------
# TaskNode: mcp_tools (strict org scoping)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tasknode_create_rejects_cross_org_inline_mcp_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_tool = _mcp_tool(org_b, name="b-mcp-tool", tool_name="b_mcp_tool")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {"mcp_tools": [{"mcp_tool": b_tool.id, "mode": "allow"}]},
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_tasknode_create_allows_same_org_inline_mcp_tool(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_tool = _mcp_tool(org_a, name="a-mcp-tool", tool_name="a_mcp_tool")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {"mcp_tools": [{"mcp_tool": a_tool.id, "mode": "allow"}]},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = TaskNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.mcp_tools.filter(mcp_tool_id=a_tool.id).exists()


@pytest.mark.django_db
def test_tasknode_update_rejects_cross_org_inline_mcp_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = TaskNode.objects.create(graph=graph, node_name="ta2")
    b_tool = _mcp_tool(org_b, name="b-mcp-tool-2", tool_name="b_mcp_tool_2")
    resp = client_a.patch(
        f"/api/tasknodes/{node.id}/",
        {"inline_surface": {"mcp_tools": [{"mcp_tool": b_tool.id, "mode": "allow"}]}},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not InlineSurface.objects.filter(task_node_id=node.id).exists()


# ---------------------------------------------------------------------------
# TaskNode: knowledge (strict org scoping)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tasknode_create_rejects_cross_org_inline_knowledge(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_collection = _collection(org_b, name="b-collection")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {"knowledge": [{"collection": b_collection.pk}]},
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_tasknode_create_allows_same_org_inline_knowledge(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_collection = _collection(org_a, name="a-collection")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {"knowledge": [{"collection": a_collection.pk}]},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = TaskNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.knowledge.filter(collection_id=a_collection.pk).exists()


@pytest.mark.django_db
def test_tasknode_update_rejects_cross_org_inline_knowledge(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = TaskNode.objects.create(graph=graph, node_name="ta3")
    b_collection = _collection(org_b, name="b-collection-2")
    resp = client_a.patch(
        f"/api/tasknodes/{node.id}/",
        {"inline_surface": {"knowledge": [{"collection": b_collection.pk}]}},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not InlineSurface.objects.filter(task_node_id=node.id).exists()


# ---------------------------------------------------------------------------
# TaskNode: storage_items (strict org scoping)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tasknode_create_rejects_cross_org_inline_storage_item(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_file = _storage_file(org_b, path="b.txt")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {"storage_items": [{"storage_file": b_file.id}]},
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_tasknode_create_allows_same_org_inline_storage_item(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_file = _storage_file(org_a, path="a.txt")
    resp = client_a.post(
        "/api/tasknodes/",
        {
            "graph": graph.id,
            "inline_surface": {"storage_items": [{"storage_file": a_file.id}]},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = TaskNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.storage_items.filter(storage_file_id=a_file.id).exists()


@pytest.mark.django_db
def test_tasknode_update_rejects_cross_org_inline_storage_item(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = TaskNode.objects.create(graph=graph, node_name="ta4")
    b_file = _storage_file(org_b, path="b2.txt")
    resp = client_a.patch(
        f"/api/tasknodes/{node.id}/",
        {"inline_surface": {"storage_items": [{"storage_file": b_file.id}]}},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not InlineSurface.objects.filter(task_node_id=node.id).exists()


# ---------------------------------------------------------------------------
# AgentNode: same four fields, create + update, cross-org + same-org
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_agentnode_create_rejects_cross_org_inline_python_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_tool = _python_tool(org_b, name="b-agent-py-tool")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {
                "python_tools": [{"python_tool": b_tool.id, "mode": "allow"}]
            },
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_agentnode_create_allows_same_org_inline_python_tool(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_tool = _python_tool(org_a, name="a-agent-py-tool")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {
                "python_tools": [{"python_tool": a_tool.id, "mode": "allow"}]
            },
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = AgentNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.python_tools.filter(python_tool_id=a_tool.id).exists()


@pytest.mark.django_db
def test_agentnode_create_allows_built_in_python_tool_from_another_org(
    client_a, org_a, org_b
):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    built_in_tool = _python_tool(org_b, built_in=True, name="agent-shared-built-in")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {
                "python_tools": [{"python_tool": built_in_tool.id, "mode": "allow"}]
            },
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = AgentNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.python_tools.filter(
        python_tool_id=built_in_tool.id
    ).exists()


@pytest.mark.django_db
def test_agentnode_update_rejects_cross_org_inline_python_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = AgentNode.objects.create(graph=graph, node_name="aa")
    b_tool = _python_tool(org_b, name="b-agent-py-tool-2")
    resp = client_a.patch(
        f"/api/agentnodes/{node.id}/",
        {
            "inline_surface": {
                "python_tools": [{"python_tool": b_tool.id, "mode": "allow"}]
            }
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentInlineSurface.objects.filter(agent_node_id=node.id).exists()


@pytest.mark.django_db
def test_agentnode_create_rejects_cross_org_inline_mcp_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_tool = _mcp_tool(org_b, name="b-agent-mcp-tool", tool_name="b_agent_mcp_tool")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {"mcp_tools": [{"mcp_tool": b_tool.id, "mode": "allow"}]},
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_agentnode_create_allows_same_org_inline_mcp_tool(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_tool = _mcp_tool(org_a, name="a-agent-mcp-tool", tool_name="a_agent_mcp_tool")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {"mcp_tools": [{"mcp_tool": a_tool.id, "mode": "allow"}]},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = AgentNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.mcp_tools.filter(mcp_tool_id=a_tool.id).exists()


@pytest.mark.django_db
def test_agentnode_update_rejects_cross_org_inline_mcp_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = AgentNode.objects.create(graph=graph, node_name="aa2")
    b_tool = _mcp_tool(org_b, name="b-agent-mcp-tool-2", tool_name="b_agent_mcp_tool_2")
    resp = client_a.patch(
        f"/api/agentnodes/{node.id}/",
        {"inline_surface": {"mcp_tools": [{"mcp_tool": b_tool.id, "mode": "allow"}]}},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentInlineSurface.objects.filter(agent_node_id=node.id).exists()


@pytest.mark.django_db
def test_agentnode_create_rejects_cross_org_inline_knowledge(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_collection = _collection(org_b, name="b-agent-collection")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {"knowledge": [{"collection": b_collection.pk}]},
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_agentnode_create_allows_same_org_inline_knowledge(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_collection = _collection(org_a, name="a-agent-collection")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {"knowledge": [{"collection": a_collection.pk}]},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = AgentNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.knowledge.filter(collection_id=a_collection.pk).exists()


@pytest.mark.django_db
def test_agentnode_update_rejects_cross_org_inline_knowledge(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = AgentNode.objects.create(graph=graph, node_name="aa3")
    b_collection = _collection(org_b, name="b-agent-collection-2")
    resp = client_a.patch(
        f"/api/agentnodes/{node.id}/",
        {"inline_surface": {"knowledge": [{"collection": b_collection.pk}]}},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentInlineSurface.objects.filter(agent_node_id=node.id).exists()


@pytest.mark.django_db
def test_agentnode_create_rejects_cross_org_inline_storage_item(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_file = _storage_file(org_b, path="agent-b.txt")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {"storage_items": [{"storage_file": b_file.id}]},
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_agentnode_create_allows_same_org_inline_storage_item(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_file = _storage_file(org_a, path="agent-a.txt")
    resp = client_a.post(
        "/api/agentnodes/",
        {
            "graph": graph.id,
            "inline_surface": {"storage_items": [{"storage_file": a_file.id}]},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    node = AgentNode.objects.get(id=resp.data["id"])
    assert node.inline_surface.storage_items.filter(storage_file_id=a_file.id).exists()


@pytest.mark.django_db
def test_agentnode_update_rejects_cross_org_inline_storage_item(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    node = AgentNode.objects.create(graph=graph, node_name="aa4")
    b_file = _storage_file(org_b, path="agent-b2.txt")
    resp = client_a.patch(
        f"/api/agentnodes/{node.id}/",
        {"inline_surface": {"storage_items": [{"storage_file": b_file.id}]}},
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not AgentInlineSurface.objects.filter(agent_node_id=node.id).exists()


# ---------------------------------------------------------------------------
# Graph bulk-save path (/graphs/{id}/save/): builds its own serializer context
# (GraphBulkSaveService._serializer_context) — a missing `request` there would
# change the answer for every field above, so exercise it directly for one
# strict field (mcp_tool) and the hybrid field (python_tool).
# ---------------------------------------------------------------------------


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


@pytest.mark.django_db
def test_bulk_save_rejects_cross_org_inline_mcp_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_tool = _mcp_tool(org_b, name="bulk-b-mcp-tool", tool_name="bulk_b_mcp_tool")
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "bulk-task-cross-org-mcp",
                "inline_surface": {
                    "mcp_tools": [{"mcp_tool": b_tool.id, "mode": "allow"}]
                },
            },
        ],
    }
    resp = client_a.post(_save_url(graph.id), payload, format="json")
    assert resp.status_code == 400, resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_bulk_save_allows_same_org_inline_mcp_tool(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_tool = _mcp_tool(org_a, name="bulk-a-mcp-tool", tool_name="bulk_a_mcp_tool")
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "bulk-task-same-org-mcp",
                "inline_surface": {
                    "mcp_tools": [{"mcp_tool": a_tool.id, "mode": "allow"}]
                },
            },
        ],
    }
    resp = client_a.post(_save_url(graph.id), payload, format="json")
    assert resp.status_code == 200, resp.data
    node = TaskNode.objects.get(graph=graph, node_name="bulk-task-same-org-mcp")
    assert node.inline_surface.mcp_tools.filter(mcp_tool_id=a_tool.id).exists()


@pytest.mark.django_db
def test_bulk_save_rejects_cross_org_inline_python_tool(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_tool = _python_tool(org_b, name="bulk-b-py-tool")
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "bulk-task-cross-org-py",
                "inline_surface": {
                    "python_tools": [{"python_tool": b_tool.id, "mode": "allow"}]
                },
            },
        ],
    }
    resp = client_a.post(_save_url(graph.id), payload, format="json")
    assert resp.status_code == 400, resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_bulk_save_allows_built_in_python_tool_from_another_org(client_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    built_in_tool = _python_tool(org_b, built_in=True, name="bulk-shared-built-in")
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "bulk-task-built-in-py",
                "inline_surface": {
                    "python_tools": [{"python_tool": built_in_tool.id, "mode": "allow"}]
                },
            },
        ],
    }
    resp = client_a.post(_save_url(graph.id), payload, format="json")
    assert resp.status_code == 200, resp.data
    node = TaskNode.objects.get(graph=graph, node_name="bulk-task-built-in-py")
    assert node.inline_surface.python_tools.filter(
        python_tool_id=built_in_tool.id
    ).exists()
