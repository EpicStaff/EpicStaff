"""
Tests for strict `output_schema` validation on TaskNode and AgentNode task
serializers.

Covers the shared `validate_output_schema` helper as exercised through:
- TaskNodeSerializer (TaskNode.output_schema)
- AgentNodeSerializer's nested `tasks` (AgentNodeTaskWriteSerializer.output_schema)
- AgentNodeTaskSerializer (standalone AgentNodeTaskViewSet.output_schema)

Accepted: {} / None, a full object schema, a scalar schema with a top-level
"type". Rejected (400): non-dict, a bare field map (no top-level "type"), and
a schema that fails jsonschema meta-validation.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory

from tables.models.graph_models import AgentNode, AgentNodeTask, Graph
from tables.serializers.model_serializers.node_serializers.basic_node_serializers import (
    AgentNodeSerializer,
    AgentNodeTaskSerializer,
    TaskNodeSerializer,
)

OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"reasoning": {"type": "string"}},
    "required": ["reasoning"],
}

SCALAR_SCHEMA = {"type": "string"}

BARE_FIELD_MAP_SCHEMA = {
    "reasoning": {"type": "string", "description": "why the answer was chosen"}
}

META_INVALID_SCHEMA = {"type": "object", "properties": "garbage"}


@pytest.fixture
def graph(db, default_org):
    return Graph.objects.create(name="output-schema-validation-graph", org=default_org)


@pytest.fixture
def agent_node(db, graph):
    return AgentNode.objects.create(graph=graph, node_name="output-schema-agent-node")


@pytest.fixture
def org_request(default_org, superadmin_user):
    """Authenticated request scoped to `default_org`, for serializers built
    directly (not through a view). `TaskNodeSerializer`/`AgentNodeSerializer`
    resolve their `graph` field's org scope from `request` via
    `OrgContextService` (see `tables/serializers/org_scoped_fields.py`) —
    without a request they deny every pk."""
    request = APIRequestFactory().post("/", HTTP_X_ORGANIZATION_ID=str(default_org.pk))
    request.user = superadmin_user
    return request


# ---------------------------------------------------------------------------
# TaskNodeSerializer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("output_schema", [{}, OBJECT_SCHEMA, SCALAR_SCHEMA])
def test_task_node_accepts_valid_output_schema(graph, output_schema, org_request):
    serializer = TaskNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "task-valid-schema",
            "output_schema": output_schema,
        },
        context={"organization": graph.org, "request": org_request},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_task_node_accepts_missing_output_schema(graph, org_request):
    serializer = TaskNodeSerializer(
        data={"graph": graph.pk, "node_name": "task-no-schema"},
        context={"organization": graph.org, "request": org_request},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_task_node_rejects_bare_field_map_with_hint(graph):
    serializer = TaskNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "task-bare-map",
            "output_schema": BARE_FIELD_MAP_SCHEMA,
        }
    )

    assert not serializer.is_valid()
    error_message = str(serializer.errors["output_schema"])
    assert "bare field map" in error_message
    assert "properties" in error_message


@pytest.mark.django_db
def test_task_node_rejects_non_dict_output_schema(graph):
    serializer = TaskNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "task-non-dict-schema",
            "output_schema": "not-a-schema",
        }
    )

    assert not serializer.is_valid()
    assert "output_schema" in serializer.errors


@pytest.mark.django_db
@pytest.mark.parametrize("output_schema", [[], 0, ""])
def test_task_node_rejects_falsy_non_dict_output_schema(graph, output_schema):
    """Falsy non-dict values ([], 0, "") are not treated as 'no enforcement' —
    only None/{} are. They must fall through to the non-dict rejection."""
    serializer = TaskNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "task-falsy-non-dict-schema",
            "output_schema": output_schema,
        }
    )

    assert not serializer.is_valid()
    assert "output_schema" in serializer.errors


@pytest.mark.django_db
def test_task_node_rejects_meta_invalid_output_schema(graph):
    serializer = TaskNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "task-meta-invalid-schema",
            "output_schema": META_INVALID_SCHEMA,
        }
    )

    assert not serializer.is_valid()
    assert "output_schema" in serializer.errors


# ---------------------------------------------------------------------------
# AgentNodeSerializer nested tasks (AgentNodeTaskWriteSerializer)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("output_schema", [{}, OBJECT_SCHEMA, SCALAR_SCHEMA])
def test_agent_node_task_accepts_valid_output_schema(graph, output_schema, org_request):
    serializer = AgentNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "agent-node-valid-task-schema",
            "tasks": [
                {
                    "name": "task-a",
                    "order": 0,
                    "output_schema": output_schema,
                }
            ],
        },
        context={"organization": graph.org, "request": org_request},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_agent_node_task_rejects_bare_field_map_with_hint(graph):
    serializer = AgentNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "agent-node-bare-map-task",
            "tasks": [
                {
                    "name": "task-a",
                    "order": 0,
                    "output_schema": BARE_FIELD_MAP_SCHEMA,
                }
            ],
        }
    )

    assert not serializer.is_valid()
    error_message = str(serializer.errors["tasks"])
    assert "bare field map" in error_message


@pytest.mark.django_db
def test_agent_node_task_rejects_non_dict_output_schema(graph):
    serializer = AgentNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "agent-node-non-dict-task",
            "tasks": [
                {
                    "name": "task-a",
                    "order": 0,
                    "output_schema": "not-a-schema",
                }
            ],
        }
    )

    assert not serializer.is_valid()
    assert "tasks" in serializer.errors


@pytest.mark.django_db
def test_agent_node_task_rejects_meta_invalid_output_schema(graph):
    serializer = AgentNodeSerializer(
        data={
            "graph": graph.pk,
            "node_name": "agent-node-meta-invalid-task",
            "tasks": [
                {
                    "name": "task-a",
                    "order": 0,
                    "output_schema": META_INVALID_SCHEMA,
                }
            ],
        }
    )

    assert not serializer.is_valid()
    assert "tasks" in serializer.errors


# ---------------------------------------------------------------------------
# AgentNodeTaskSerializer (standalone AgentNodeTaskViewSet)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("output_schema", [{}, OBJECT_SCHEMA, SCALAR_SCHEMA])
def test_agent_node_task_serializer_accepts_valid_output_schema(
    agent_node, output_schema
):
    serializer = AgentNodeTaskSerializer(
        data={
            "agent_node": agent_node.id,
            "name": "task-a",
            "order": 0,
            "output_schema": output_schema,
        }
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_agent_node_task_serializer_rejects_bare_field_map_with_hint(agent_node):
    serializer = AgentNodeTaskSerializer(
        data={
            "agent_node": agent_node.id,
            "name": "task-a",
            "order": 0,
            "output_schema": BARE_FIELD_MAP_SCHEMA,
        }
    )

    assert not serializer.is_valid()
    error_message = str(serializer.errors["output_schema"])
    assert "bare field map" in error_message


@pytest.mark.django_db
def test_agent_node_task_serializer_rejects_non_dict_output_schema(agent_node):
    serializer = AgentNodeTaskSerializer(
        data={
            "agent_node": agent_node.id,
            "name": "task-a",
            "order": 0,
            "output_schema": "not-a-schema",
        }
    )

    assert not serializer.is_valid()
    assert "output_schema" in serializer.errors


@pytest.mark.django_db
def test_agent_node_task_serializer_rejects_meta_invalid_output_schema(agent_node):
    serializer = AgentNodeTaskSerializer(
        data={
            "agent_node": agent_node.id,
            "name": "task-a",
            "order": 0,
            "output_schema": META_INVALID_SCHEMA,
        }
    )

    assert not serializer.is_valid()
    assert "output_schema" in serializer.errors
