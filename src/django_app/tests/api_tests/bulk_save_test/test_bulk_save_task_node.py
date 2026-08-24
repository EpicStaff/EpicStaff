"""
Integration tests for TaskNode in the graph bulk-save endpoint
(POST /graphs/{id}/save/) and the graph/{id}/ detail response.

Covers:
- Create: plain, with surface_list, with inline_surface payload
- Update: replace surface_list, replace inline_surface content, null clears it
- Delete: node + InlineSurface + content rows removed via deleted.task_node_ids
- temp_id: task node created with temp_id, edge wired to the real id
- Validation surfaced through bulk save: cross-org surface, foreign-agent-owned
  surface, duplicate inline python_tool ids
- GET /graphs/{id}/ and the bulk-save response both include task_node_list
"""

import pytest
from django.urls import reverse
from rest_framework import status

from agents.models import AgentDefinition, InlineSurface, Surface
from tables.models.graph_models import Edge, TaskNode
from tests.fixtures import *  # noqa: F401,F403


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _detail_url(graph_id: int) -> str:
    return reverse("graphs-detail", args=[graph_id])


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_task_node(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {"graph": graph.id, "node_name": "task-plain"},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert TaskNode.objects.filter(graph=graph, node_name="task-plain").count() == 1


@pytest.mark.django_db
def test_create_task_node_with_surface_list(
    auth_client, graph, shared_surface, agent_owned_surface, agent_definition
):
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "task-with-surfaces",
                "agent_definition": agent_definition.id,
                "surface_list": [shared_surface.id, agent_owned_surface.id],
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    node = TaskNode.objects.get(graph=graph, node_name="task-with-surfaces")
    assert set(node.surface_list.values_list("id", flat=True)) == {
        shared_surface.id,
        agent_owned_surface.id,
    }


@pytest.mark.django_db
def test_create_task_node_with_inline_surface(auth_client, graph, py_tool):
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "task-inline",
                "inline_surface": {
                    "instructions": "be concise",
                    "python_tools": [{"python_tool": py_tool.id, "mode": "allow"}],
                },
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    node = TaskNode.objects.get(graph=graph, node_name="task-inline")
    inline = InlineSurface.objects.get(task_node=node)
    assert inline.instructions == "be concise"
    assert inline.python_tools.count() == 1


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_task_node_replaces_surface_list(
    auth_client, graph, task_node, shared_surface
):
    surface_b = Surface.objects.create(
        organization=shared_surface.organization,
        name="bulk-save-shared-surface-b",
        owner_agent=None,
    )
    task_node.surface_list.add(shared_surface)

    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "id": task_node.id,
                "graph": graph.id,
                "node_name": task_node.node_name,
                "surface_list": [surface_b.id],
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    task_node.refresh_from_db()
    assert set(task_node.surface_list.values_list("id", flat=True)) == {surface_b.id}


@pytest.mark.django_db
def test_update_task_node_replaces_inline_surface_content(
    auth_client, graph, task_node, py_tool, mcp_tool
):
    InlineSurface.objects.create(task_node=task_node)

    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "id": task_node.id,
                "graph": graph.id,
                "node_name": task_node.node_name,
                "inline_surface": {
                    "python_tools": [],
                    "mcp_tools": [{"mcp_tool": mcp_tool.id, "mode": "allow"}],
                },
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    inline = InlineSurface.objects.get(task_node=task_node)
    assert inline.python_tools.count() == 0
    assert inline.mcp_tools.count() == 1


@pytest.mark.django_db
def test_update_task_node_inline_surface_null_deletes_it(auth_client, graph, task_node):
    InlineSurface.objects.create(task_node=task_node, instructions="drop me")

    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "id": task_node.id,
                "graph": graph.id,
                "node_name": task_node.node_name,
                "inline_surface": None,
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not InlineSurface.objects.filter(task_node=task_node).exists()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_task_node_removes_inline_surface_and_content(
    auth_client, graph, task_node, py_tool
):
    inline = InlineSurface.objects.create(task_node=task_node)
    inline.python_tools.create(python_tool=py_tool, mode="allow")

    payload = {
        "save_version": graph.save_version,
        "deleted": {"task_node_ids": [task_node.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not TaskNode.objects.filter(id=task_node.id).exists()
    assert not InlineSurface.objects.filter(id=inline.id).exists()


# ---------------------------------------------------------------------------
# temp_id wiring
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_task_node_with_temp_id_wires_edge(auth_client, graph, crew_node):
    temp_id = "aaaa1111-0000-0000-0000-000000000099"
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "task-temp-id",
                "temp_id": temp_id,
            },
        ],
        "edge_list": [
            {
                "graph": graph.id,
                "start_temp_id": temp_id,
                "end_node_id": crew_node.id,
            }
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    new_node = TaskNode.objects.get(graph=graph, node_name="task-temp-id")
    assert Edge.objects.filter(
        graph=graph, start_node_id=new_node.id, end_node_id=crew_node.id
    ).exists()


# ---------------------------------------------------------------------------
# Validation through bulk save
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_task_node_rejects_cross_org_surface(
    auth_client, graph, bulk_save_org, other_org_surface
):
    """SurfaceValidationError (an APIException, not serializers.ValidationError)
    is raised from TaskNodeSerializer.validate() and propagates past
    serializer.is_valid() straight to DRF's exception handler as a top-level
    400 — same shape as the standalone /api/tasknodes/ endpoint, not nested
    under errors.task_node_list like ordinary field validation errors."""
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "task-cross-org",
                "surface_list": [other_org_surface.id],
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_create_task_node_rejects_foreign_agent_owned_surface(
    auth_client, graph, bulk_save_org, agent_definition, agent_owned_surface
):
    other_agent = AgentDefinition.objects.create(
        organization=agent_definition.organization,
        name="bulk-save-other-agent",
        instructions="do other things",
    )

    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "task-wrong-agent",
                "agent_definition": other_agent.id,
                "surface_list": [agent_owned_surface.id],
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_create_task_node_rejects_duplicate_inline_python_tools(
    auth_client, graph, py_tool
):
    """SurfaceValidator raises SurfaceValidationError (an APIException, not a
    DRF serializers.ValidationError) from InlineSurfaceWriteSerializer.validate().
    It is not caught by serializer.is_valid() or BulkSaveValidationError, so it
    propagates straight to DRF's exception handler as a top-level 400 — same
    shape as the standalone /api/tasknodes/ endpoint, not nested under
    errors.task_node_list like ordinary field validation errors."""
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {
                "graph": graph.id,
                "node_name": "task-dup-inline-tool",
                "inline_surface": {
                    "python_tools": [
                        {"python_tool": py_tool.id, "mode": "allow"},
                        {"python_tool": py_tool.id, "mode": "deny"},
                    ]
                },
            },
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "inline_surface" in response.data["message"]


# ---------------------------------------------------------------------------
# GET /graphs/{id}/ and bulk-save response shape
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_graph_detail_returns_task_node_list(
    auth_client, graph, task_node, shared_surface
):
    task_node.surface_list.add(shared_surface)
    InlineSurface.objects.create(task_node=task_node, instructions="hello")

    response = auth_client.get(_detail_url(graph.id))

    assert response.status_code == status.HTTP_200_OK, response.content
    task_nodes = response.data["task_node_list"]
    assert len(task_nodes) == 1
    assert task_nodes[0]["surface_list"] == [shared_surface.id]
    assert task_nodes[0]["inline_surface"]["instructions"] == "hello"


@pytest.mark.django_db
def test_bulk_save_response_includes_task_node_list(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "task_node_list": [
            {"graph": graph.id, "node_name": "task-in-response"},
        ],
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    task_nodes = response.data["task_node_list"]
    assert len(task_nodes) == 1
    assert task_nodes[0]["node_name"] == "task-in-response"
