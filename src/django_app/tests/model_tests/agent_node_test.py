"""
Integration tests for AgentNode Step 1 storage.

Covers:
- AgentNodeSerializer create with nested tasks resolving intra-node context
  refs from temp_id
- Duplicate task names within one node payload rejected
- Forward/self context references rejected
- Update: upsert-by-id semantics (update existing, add new, delete omitted)
- AgentInlineSurfaceService.apply: create / replace / delete
- bulk-save integration: POST /graphs/{id}/save/ with agent_node_list
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.models.agent_models import AgentDefinition
from tables.models.agent_models.surface_models import AgentInlineSurface
from tables.models.graph_models import AgentNode, AgentNodeTask, Graph
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization
from tables.serializers.model_serializers.node_serializers.basic_node_serializers import (
    AgentNodeSerializer,
)
from tables.services.agent_inline_surface_service import AgentInlineSurfaceService
from tables.services.agent_node_payload_service import AgentNodePayloadService
from tables.services.converter_service import ConverterService
from tables.services.node_surface_service import NodeSurfaceService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def org(db):
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def graph(db, org):
    return Graph.objects.create(name="agent-node-graph")


@pytest.fixture
def agent(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="agent-node-agent",
        instructions="do things",
    )


@pytest.fixture
def agent_node(db, graph):
    return AgentNode.objects.create(graph=graph, node_name="agent-node-1")


@pytest.fixture
def py_tool(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="agent-node-py-tool",
        description="test",
        python_code=code,
    )


@pytest.fixture
def mcp_tool(db):
    return McpTool.objects.create(
        name="agent-node-mcp-tool",
        transport="http://localhost/sse",
        tool_name="agent_node_tool",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_serializer(data, instance=None, context=None):
    return AgentNodeSerializer(
        instance=instance,
        data=data,
        context=context or {},
        partial=instance is not None,
    )


# ---------------------------------------------------------------------------
# 1. Create with nested tasks — intra-node context resolved from temp_id
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_with_nested_tasks_resolves_context_from_temp_id(graph):
    temp_id_a = uuid.uuid4()
    temp_id_b = uuid.uuid4()

    data = {
        "graph": graph.pk,
        "node_name": "agent-node-context",
        "tasks": [
            {"temp_id": str(temp_id_a), "name": "task-a", "order": 0},
            {
                "temp_id": str(temp_id_b),
                "name": "task-b",
                "order": 1,
                "context_task_temp_ids": [str(temp_id_a)],
            },
        ],
    }

    serializer = _make_serializer(data)
    assert serializer.is_valid(), serializer.errors
    node = serializer.save()

    task_a = AgentNodeTask.objects.get(agent_node=node, name="task-a")
    task_b = AgentNodeTask.objects.get(agent_node=node, name="task-b")

    assert list(task_b.context_tasks.values_list("id", flat=True)) == [task_a.id]


# ---------------------------------------------------------------------------
# 2. Duplicate task names rejected
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_rejects_duplicate_task_names(graph):
    data = {
        "graph": graph.pk,
        "node_name": "agent-node-dup-names",
        "tasks": [
            {"name": "same-name", "order": 0},
            {"name": "same-name", "order": 1},
        ],
    }

    serializer = _make_serializer(data)
    assert not serializer.is_valid()
    assert "tasks" in serializer.errors


# ---------------------------------------------------------------------------
# 3. Forward / self context references rejected
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_rejects_context_ref_to_later_or_equal_order_task(graph):
    temp_id_a = uuid.uuid4()
    temp_id_b = uuid.uuid4()

    data = {
        "graph": graph.pk,
        "node_name": "agent-node-forward-ref",
        "tasks": [
            {
                "temp_id": str(temp_id_a),
                "name": "task-a",
                "order": 0,
                "context_task_temp_ids": [str(temp_id_b)],
            },
            {"temp_id": str(temp_id_b), "name": "task-b", "order": 0},
        ],
    }

    serializer = _make_serializer(data)
    assert not serializer.is_valid()
    assert "tasks" in serializer.errors


# ---------------------------------------------------------------------------
# 4. Update: upsert-by-id semantics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_upserts_tasks_by_id_and_deletes_omitted(agent_node):
    task_to_keep = AgentNodeTask.objects.create(
        agent_node=agent_node, name="keep-me", order=0
    )
    task_to_update = AgentNodeTask.objects.create(
        agent_node=agent_node, name="update-me", order=1
    )
    task_to_delete = AgentNodeTask.objects.create(
        agent_node=agent_node, name="delete-me", order=2
    )

    new_temp_id = uuid.uuid4()
    data = {
        "tasks": [
            {"id": task_to_keep.id, "name": "keep-me", "order": 0},
            {
                "id": task_to_update.id,
                "name": "update-me-renamed",
                "order": 1,
                "context_task_ids": [task_to_keep.id],
            },
            {"temp_id": str(new_temp_id), "name": "new-task", "order": 2},
        ]
    }

    serializer = _make_serializer(data, instance=agent_node)
    assert serializer.is_valid(), serializer.errors
    node = serializer.save()

    remaining_names = set(node.tasks.values_list("name", flat=True))
    assert remaining_names == {"keep-me", "update-me-renamed", "new-task"}
    assert not AgentNodeTask.objects.filter(id=task_to_delete.id).exists()

    task_to_update.refresh_from_db()
    assert task_to_update.name == "update-me-renamed"
    assert list(task_to_update.context_tasks.values_list("id", flat=True)) == [
        task_to_keep.id
    ]


@pytest.mark.django_db
def test_update_reorders_surviving_tasks(agent_node):
    task_a = AgentNodeTask.objects.create(agent_node=agent_node, name="task-a", order=0)
    task_b = AgentNodeTask.objects.create(agent_node=agent_node, name="task-b", order=1)

    data = {
        "tasks": [
            {"id": task_a.id, "name": "task-a", "order": 1},
            {"id": task_b.id, "name": "task-b", "order": 0},
        ]
    }

    serializer = _make_serializer(data, instance=agent_node)
    assert serializer.is_valid(), serializer.errors
    serializer.save()

    task_a.refresh_from_db()
    task_b.refresh_from_db()
    assert task_a.order == 1
    assert task_b.order == 0


# ---------------------------------------------------------------------------
# 5. AgentInlineSurfaceService.apply — create / replace / delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_inline_surface_service_apply_create(agent_node, py_tool):
    inline = AgentInlineSurfaceService.apply(
        agent_node=agent_node,
        data={
            "instructions": "be concise",
            "python_tools": [{"python_tool": py_tool, "mode": "allow"}],
        },
    )

    assert inline.instructions == "be concise"
    assert inline.python_tools.count() == 1


@pytest.mark.django_db
def test_inline_surface_service_apply_replace_with_fewer_items(
    agent_node, py_tool, mcp_tool
):
    AgentInlineSurfaceService.apply(
        agent_node=agent_node,
        data={
            "python_tools": [{"python_tool": py_tool, "mode": "allow"}],
            "mcp_tools": [{"mcp_tool": mcp_tool, "mode": "allow"}],
        },
    )

    inline = AgentInlineSurfaceService.apply(
        agent_node=agent_node,
        data={"mcp_tools": [{"mcp_tool": mcp_tool, "mode": "deny"}]},
    )

    assert inline.python_tools.count() == 0
    assert inline.mcp_tools.count() == 1
    assert inline.mcp_tools.first().mode == "deny"


@pytest.mark.django_db
def test_inline_surface_service_apply_delete_cascades_children(agent_node, py_tool):
    inline = AgentInlineSurfaceService.apply(
        agent_node=agent_node,
        data={"python_tools": [{"python_tool": py_tool, "mode": "allow"}]},
    )
    inline_id = inline.id

    result = AgentInlineSurfaceService.apply(agent_node=agent_node, data=None)

    assert result is None
    assert not AgentInlineSurface.objects.filter(id=inline_id).exists()


# ---------------------------------------------------------------------------
# 6. bulk-save integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_save_creates_agent_node_with_tasks_and_inline_surface(
    client, graph, py_tool
):
    task_a_temp_id = str(uuid.uuid4())
    task_b_temp_id = str(uuid.uuid4())

    payload = {
        "save_version": graph.save_version,
        "agent_node_list": [
            {
                "graph": graph.id,
                "node_name": "agent-node-bulk-save",
                "tasks": [
                    {
                        "temp_id": task_a_temp_id,
                        "name": "task-a",
                        "order": 0,
                    },
                    {
                        "temp_id": task_b_temp_id,
                        "name": "task-b",
                        "order": 1,
                        "context_task_temp_ids": [task_a_temp_id],
                    },
                ],
                "inline_surface": {
                    "instructions": "be concise",
                    "python_tools": [{"python_tool": py_tool.id, "mode": "allow"}],
                },
            },
        ],
    }

    response = client.post(f"/api/graphs/{graph.id}/save/", payload, format="json")

    assert response.status_code == 200, response.data

    node = AgentNode.objects.get(graph=graph, node_name="agent-node-bulk-save")
    task_a = AgentNodeTask.objects.get(agent_node=node, name="task-a")
    task_b = AgentNodeTask.objects.get(agent_node=node, name="task-b")
    assert list(task_b.context_tasks.values_list("id", flat=True)) == [task_a.id]

    inline = AgentInlineSurface.objects.get(agent_node=node)
    assert inline.instructions == "be concise"
    assert inline.python_tools.count() == 1

    detail_response = client.get(f"/api/graphs/{graph.id}/")
    assert detail_response.status_code == 200, detail_response.data
    agent_nodes = detail_response.data["agent_node_list"]
    assert len(agent_nodes) == 1
    assert {task["name"] for task in agent_nodes[0]["tasks"]} == {"task-a", "task-b"}


# ---------------------------------------------------------------------------
# 7. AgentNodePayloadService.build_agent_node_data
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_agent_node_data_orders_tasks_and_resolves_context_to_names(
    agent_node, agent
):
    agent_node.agent_definition = agent
    agent_node.save()

    task_a = AgentNodeTask.objects.create(agent_node=agent_node, name="task-a", order=0)
    task_b = AgentNodeTask.objects.create(
        agent_node=agent_node, name="task-b", order=1, instructions="do b"
    )
    task_b.context_tasks.add(task_a)

    AgentInlineSurfaceService.apply(
        agent_node=agent_node,
        data={"instructions": "be concise"},
    )

    service = AgentNodePayloadService(ConverterService())
    data = service.build_agent_node_data(
        agent_node, node_name="agent-node-1 #1", graph_id=None, session_id=None
    )

    assert data.node_name == "agent-node-1 #1"
    assert data.agent_definition is not None
    assert data.agent_definition.id == agent.id
    assert [task.name for task in data.tasks] == ["task-a", "task-b"]
    assert data.tasks[1].instructions == "do b"
    assert data.tasks[1].context_tasks == ["task-a"]
    assert data.tasks[0].context_tasks == []
    assert data.surface.instructions == "be concise"


@pytest.mark.django_db
def test_build_agent_node_data_without_agent_definition_is_none(agent_node):
    service = AgentNodePayloadService(ConverterService())
    data = service.build_agent_node_data(
        agent_node, node_name="agent-node-1 #1", graph_id=None, session_id=None
    )

    assert data.agent_definition is None
    assert data.tasks == []


# ---------------------------------------------------------------------------
# 8. NodeSurfaceService.build_combined_surface uses the AgentInlineSurface serializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_combined_surface_uses_agent_inline_surface_serializer(agent_node):
    AgentInlineSurfaceService.apply(
        agent_node=agent_node,
        data={"instructions": "answer briefly"},
    )
    agent_node.refresh_from_db()

    combined = NodeSurfaceService.build_combined_surface(agent_node)

    assert combined["instructions"] == "answer briefly"
