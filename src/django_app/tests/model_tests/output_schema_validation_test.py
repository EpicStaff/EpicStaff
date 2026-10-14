"""
Strict `output_schema` validation, shared by every serializer that accepts one:
TaskNodeSerializer, AgentNodeSerializer's nested `tasks`, and the standalone
AgentNodeTaskSerializer.

Accepted: {} / omitted, a full object schema, a scalar schema with a top-level
"type". Rejected (400): non-dict (falsy ones too — only None/{} mean "no
enforcement"), a bare field map (no top-level "type"), and a schema that fails
jsonschema meta-validation.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory

from tables.models.graph_models import AgentNode, Graph
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
BARE_FIELD_MAP_SCHEMA = {"reasoning": {"type": "string", "description": "why the answer was chosen"}}
META_INVALID_SCHEMA = {"type": "object", "properties": "garbage"}
OMITTED = object()


@pytest.fixture
def graph(db, default_org):
    return Graph.objects.create(name="output-schema-validation-graph", org=default_org)


@pytest.fixture
def org_request(default_org, superadmin_user):
    """Authenticated request scoped to `default_org`, for serializers built
    directly (not through a view): their `graph` field resolves org scope from
    `request` via `OrgContextService` and denies every pk without one."""
    request = APIRequestFactory().post("/", HTTP_X_ORGANIZATION_ID=str(default_org.pk))
    request.user = superadmin_user
    return request


def _with_schema(fields, output_schema):
    return fields if output_schema is OMITTED else {**fields, "output_schema": output_schema}


def _task_node(graph, org_request, output_schema):
    return TaskNodeSerializer(
        data=_with_schema({"graph": graph.pk, "node_name": "task"}, output_schema),
        context={"organization": graph.org, "request": org_request},
    ), "output_schema"


def _agent_node_task(graph, org_request, output_schema):
    return AgentNodeSerializer(
        data={"graph": graph.pk, "node_name": "agent-node", "tasks": [_with_schema({"name": "task-a", "order": 0}, output_schema)]},
        context={"organization": graph.org, "request": org_request},
    ), "tasks"


def _standalone_agent_task(graph, org_request, output_schema):
    agent_node = AgentNode.objects.create(graph=graph, node_name="output-schema-agent-node")
    return AgentNodeTaskSerializer(
        data=_with_schema({"agent_node": agent_node.id, "name": "task-a", "order": 0}, output_schema)
    ), "output_schema"


SERIALIZERS = pytest.mark.parametrize(
    "build", [_task_node, _agent_node_task, _standalone_agent_task], ids=["task-node", "agent-node-task", "standalone-agent-task"]
)


@SERIALIZERS
@pytest.mark.parametrize(
    "output_schema", [OMITTED, {}, OBJECT_SCHEMA, SCALAR_SCHEMA], ids=["omitted", "empty", "object", "scalar"]
)
@pytest.mark.django_db
def test_valid_output_schema_is_accepted(graph, org_request, build, output_schema):
    serializer, _ = build(graph, org_request, output_schema)

    assert serializer.is_valid(), serializer.errors


@SERIALIZERS
@pytest.mark.parametrize(
    "output_schema",
    ["not-a-schema", [], 0, "", META_INVALID_SCHEMA, BARE_FIELD_MAP_SCHEMA],
    ids=["string", "empty-list", "zero", "empty-string", "meta-invalid", "bare-field-map"],
)
@pytest.mark.django_db
def test_invalid_output_schema_is_rejected(graph, org_request, build, output_schema):
    serializer, error_field = build(graph, org_request, output_schema)

    assert not serializer.is_valid()
    assert list(serializer.errors) == [error_field]
    if output_schema is BARE_FIELD_MAP_SCHEMA:
        # The likely mistake gets a hint about wrapping the fields in "properties".
        assert "bare field map" in str(serializer.errors[error_field])
        assert "properties" in str(serializer.errors[error_field])
