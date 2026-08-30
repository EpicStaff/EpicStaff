from loguru import logger
from collections import Counter

import jsonschema
from django.db import transaction
from rest_framework import serializers

from tables.serializers.model_serializers.python_serializers import PythonCodeSerializer
from tables.models.crew_models import Crew
from tables.models.llm_models import LLMConfig
from tables.serializers.model_serializers.crew_serializers import (
    CrewSerializer,
)
from tables.models.graph_models import (
    AgentNode,
    AgentNodeTask,
    AudioTranscriptionNode,
    CrewNode,
    Edge,
    FileExtractorNode,
    Graph,
    PythonNode,
    SubGraphNode,
    TaskNode,
)
from tables.serializers.base_serializer import (
    BaseGraphEntityMixin,
    ContentHashWritableMixin,
)
from tables.serializers.org_scoped_fields import (
    OrganizationScopedPrimaryKeyRelatedField,
    OrgScopedPrimaryKeyRelatedField,
    resolve_active_org_id,
)
from agents.models.agent_models import AgentDefinition
from agents.models.surface_models import Surface
from agents.serializers.inline_surface_serializers import (
    AgentInlineSurfaceReadSerializer,
    AgentInlineSurfaceWriteSerializer,
    InlineSurfaceReadSerializer,
    InlineSurfaceWriteSerializer,
)
from tables.serializers.utils.mixins import (
    NestedPythonCodeMixin,
    assert_node_ref_in_graph,
)
from agents.services.agent_inline_surface_service import AgentInlineSurfaceService
from agents.services.inline_surface_service import InlineSurfaceService
from agents.validators.surface_validator import SurfaceValidator

# Top-level keywords a real JSON Schema might use even without "type" (e.g.
# "$ref", "allOf"). Used only to tell a bare field map ("reasoning":
# {"type": "string"}) apart from a legitimate-but-incomplete schema for the
# purpose of a tailored error message.
_JSON_SCHEMA_KEYWORDS = {
    "type",
    "$ref",
    "$schema",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "enum",
    "const",
    "properties",
    "items",
    "additionalProperties",
    "required",
    "patternProperties",
    "definitions",
    "$defs",
}


def validate_output_schema(value):
    """Shared `output_schema` validator for TaskNode and AgentNode task serializers.

    Accepts `{}`/None (no enforcement) or a dict with a top-level "type" key
    that passes jsonschema meta-validation. Rejects everything else with a
    precise message, including a tailored hint when the value looks like a
    bare field map instead of a full JSON Schema.
    """
    if value is None or value == {}:
        return value

    if not isinstance(value, dict):
        raise serializers.ValidationError(
            "output_schema must be {} or a full JSON Schema object, "
            f"got {type(value).__name__}."
        )

    if "type" not in value:
        is_bare_field_map = all(
            isinstance(field_value, dict) for field_value in value.values()
        ) and not (_JSON_SCHEMA_KEYWORDS & value.keys())

        if is_bare_field_map:
            raise serializers.ValidationError(
                'output_schema must be {} or a full JSON Schema with a top-level "type", '
                'e.g. {"type": "object", "properties": {...}, "required": [...]}. '
                'Got a bare field map — wrap your fields under "properties".'
            )

        raise serializers.ValidationError(
            'output_schema must be {} or a full JSON Schema with a top-level "type" key, '
            'e.g. {"type": "object", "properties": {...}, "required": [...]}.'
        )

    try:
        jsonschema.validators.validator_for(value).check_schema(value)
    except jsonschema.exceptions.SchemaError as error:
        raise serializers.ValidationError(
            f"output_schema is not a valid JSON Schema: {error.message}"
        ) from error

    return value


class CrewNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    """
    DEPRECATED: CrewNodeSerializer is deprecated. Use AgentNodeSerializer or
    TaskNodeSerializer instead. Exists only for backward compatibility with
    existing CrewNode rows.
    """

    crew = CrewSerializer(read_only=True)
    crew_id = serializers.IntegerField(write_only=True)
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = CrewNode
        fields = "__all__"
        read_only_fields = ["crew"]

    def validate_crew_id(self, value):
        # Org isolation: the referenced crew must be in the caller's active org.
        # Out-of-org and non-existent ids are rejected identically (no leak).
        request = self.context.get("request")
        if request is None:
            # No request in context => org scope cannot be applied. Deny (fail-safe)
            # instead of allowing any crew, and log so the missing context surfaces.
            logger.warning(
                "CrewNodeSerializer.validate_crew_id was resolved without a request "
                "in the serializer context; rejecting crew_id because org scope "
                "cannot be applied. Construct the serializer with the request in "
                "its context."
            )
            raise serializers.ValidationError("Invalid crew_id: crew does not exist.")
        crews = Crew.objects.only("id").filter(org_id=resolve_active_org_id(request))
        if not crews.filter(id=value).exists():
            raise serializers.ValidationError("Invalid crew_id: crew does not exist.")
        return value

    def update(self, instance, validated_data):
        if "crew_id" in validated_data:
            instance.crew_id = validated_data["crew_id"]
        return super().update(instance, validated_data)


class PythonNodeSerializer(
    ContentHashWritableMixin, NestedPythonCodeMixin, serializers.ModelSerializer
):
    python_code = PythonCodeSerializer()
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = PythonNode
        fields = "__all__"


class FileExtractorNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = FileExtractorNode
        fields = "__all__"


class AudioTranscriptionNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = AudioTranscriptionNode
        fields = "__all__"


class EdgeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = Edge
        fields = "__all__"

    def validate(self, attrs):
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        for field in ("start_node_id", "end_node_id"):
            node_id = attrs.get(field, getattr(self.instance, field, None))
            assert_node_ref_in_graph(node_id, graph, field)
        return attrs


class TaskNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    inline_surface = InlineSurfaceWriteSerializer(
        required=False, allow_null=True, write_only=True
    )
    # Org isolation: agent_definition/surface_list/graph must belong to the
    # caller's active org — a cross-org pk is rejected exactly like a
    # non-existent one (no leak).
    agent_definition = OrganizationScopedPrimaryKeyRelatedField(
        queryset=AgentDefinition.objects.all(), required=False, allow_null=True
    )
    surface_list = OrganizationScopedPrimaryKeyRelatedField(
        queryset=Surface.objects.all(), many=True, required=False
    )
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = TaskNode
        fields = "__all__"

    def validate_output_schema(self, value):
        return validate_output_schema(value)

    def validate(self, attrs):
        organization = self.context.get("organization")
        if organization is None:
            return attrs

        if "surface_list" in attrs:
            surfaces = attrs["surface_list"]
        elif "agent_definition" in attrs and self.instance is not None:
            surfaces = list(self.instance.surface_list.all())
        else:
            surfaces = None

        if not surfaces:
            return attrs

        if "agent_definition" in attrs:
            agent_definition = attrs["agent_definition"]
        else:
            agent_definition = self.instance.agent_definition if self.instance else None

        SurfaceValidator.validate_task_node_surfaces(
            surfaces=surfaces,
            agent_definition=agent_definition,
            organization=organization,
        )

        return attrs

    def create(self, validated_data):
        has_inline = "inline_surface" in validated_data
        inline_data = validated_data.pop("inline_surface", None)

        with transaction.atomic():
            node = super().create(validated_data)
            if has_inline:
                # Prime select_related cache so to_representation avoids a query.
                node.inline_surface = InlineSurfaceService.apply(
                    task_node=node, data=inline_data
                )

        return node

    def update(self, instance, validated_data):
        has_inline = "inline_surface" in validated_data
        inline_data = validated_data.pop("inline_surface", None)

        with transaction.atomic():
            node = super().update(instance, validated_data)
            if has_inline:
                # Refresh stale select_related cache; None evicts it so to_representation re-queries.
                node.inline_surface = InlineSurfaceService.apply(
                    task_node=node, data=inline_data
                )

        return node

    def to_representation(self, instance):
        data = super().to_representation(instance)
        inline = getattr(instance, "inline_surface", None)
        data["inline_surface"] = (
            InlineSurfaceReadSerializer(inline).data if inline else None
        )
        return data


class AgentNodeTaskWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    temp_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    name = serializers.CharField(max_length=255)
    order = serializers.IntegerField(min_value=0)
    instructions = serializers.CharField(required=False, default="", allow_blank=True)
    output_schema = serializers.JSONField(required=False, default=dict)
    context_task_temp_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, write_only=True
    )
    context_task_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list, write_only=True
    )

    def validate_output_schema(self, value):
        return validate_output_schema(value)


class AgentNodeTaskReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentNodeTask
        fields = [
            "id",
            "name",
            "order",
            "instructions",
            "output_schema",
            "context_tasks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AgentNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    tasks = AgentNodeTaskWriteSerializer(many=True, required=False)
    inline_surface = AgentInlineSurfaceWriteSerializer(
        required=False, allow_null=True, write_only=True
    )
    # Org isolation: agent_definition/surface_list/graph must belong to the
    # caller's active org — a cross-org pk is rejected exactly like a
    # non-existent one (no leak).
    agent_definition = OrganizationScopedPrimaryKeyRelatedField(
        queryset=AgentDefinition.objects.all(), required=False, allow_null=True
    )
    surface_list = OrganizationScopedPrimaryKeyRelatedField(
        queryset=Surface.objects.all(), many=True, required=False
    )
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = AgentNode
        fields = "__all__"

    def validate(self, attrs):
        if "tasks" in attrs:
            self._validate_tasks(attrs["tasks"])

        organization = self.context.get("organization")
        if organization is None:
            return attrs

        if "surface_list" in attrs:
            surfaces = attrs["surface_list"]
        elif "agent_definition" in attrs and self.instance is not None:
            surfaces = list(self.instance.surface_list.all())
        else:
            surfaces = None

        if not surfaces:
            return attrs

        if "agent_definition" in attrs:
            agent_definition = attrs["agent_definition"]
        else:
            agent_definition = self.instance.agent_definition if self.instance else None

        SurfaceValidator.validate_agent_node_surfaces(
            surfaces=surfaces,
            agent_definition=agent_definition,
            organization=organization,
        )

        return attrs

    @staticmethod
    def _validate_tasks(tasks_data):
        names = [task["name"] for task in tasks_data]
        duplicate_names = [name for name, count in Counter(names).items() if count > 1]

        if duplicate_names:
            raise serializers.ValidationError(
                {"tasks": f"Duplicate task names: {sorted(duplicate_names)}"}
            )

        order_by_temp_id = {
            task["temp_id"]: task["order"] for task in tasks_data if task.get("temp_id")
        }
        order_by_id = {
            task["id"]: task["order"] for task in tasks_data if task.get("id")
        }

        for task in tasks_data:
            order = task["order"]

            for ref_temp_id in task.get("context_task_temp_ids", []):
                if (
                    ref_temp_id not in order_by_temp_id
                    or order_by_temp_id[ref_temp_id] >= order
                ):
                    raise serializers.ValidationError(
                        {
                            "tasks": f"context_task_temp_ids must reference an earlier sibling task (temp_id={ref_temp_id})."
                        }
                    )

            for ref_id in task.get("context_task_ids", []):
                if ref_id not in order_by_id or order_by_id[ref_id] >= order:
                    raise serializers.ValidationError(
                        {
                            "tasks": f"context_task_ids must reference an earlier sibling task (id={ref_id})."
                        }
                    )

    def create(self, validated_data):
        tasks_data = validated_data.pop("tasks", [])
        has_inline = "inline_surface" in validated_data
        inline_data = validated_data.pop("inline_surface", None)

        with transaction.atomic():
            node = super().create(validated_data)
            self._save_tasks(node, tasks_data)
            if has_inline:
                # Prime select_related cache so to_representation avoids a query.
                node.inline_surface = AgentInlineSurfaceService.apply(
                    agent_node=node, data=inline_data
                )

        return node

    def update(self, instance, validated_data):
        has_tasks = "tasks" in validated_data
        tasks_data = validated_data.pop("tasks", None)
        has_inline = "inline_surface" in validated_data
        inline_data = validated_data.pop("inline_surface", None)

        with transaction.atomic():
            node = super().update(instance, validated_data)
            if has_tasks:
                self._save_tasks(node, tasks_data)
            if has_inline:
                # Refresh stale select_related cache; None evicts it so to_representation re-queries.
                node.inline_surface = AgentInlineSurfaceService.apply(
                    agent_node=node, data=inline_data
                )

        return node

    @staticmethod
    def _save_tasks(node, tasks_data):
        """Upsert tasks by id, delete siblings missing from the payload, then
        resolve each task's context_tasks from temp_id/id references."""
        existing_tasks = {task.id: task for task in node.tasks.all()}
        incoming_ids = {
            task_data["id"] for task_data in tasks_data if task_data.get("id")
        }
        stale_ids = [
            task_id for task_id in existing_tasks if task_id not in incoming_ids
        ]

        # Delete omitted siblings before upserting so freed `order` values are
        # available for updated/new tasks (unique constraint on agent_node+order).
        if stale_ids:
            AgentNodeTask.objects.filter(id__in=stale_ids).delete()
            for task_id in stale_ids:
                del existing_tasks[task_id]

        saved_tasks = []
        temp_id_to_task_id = {}

        for task_data in tasks_data:
            task_id = task_data.get("id")

            if task_id and task_id in existing_tasks:
                task = existing_tasks[task_id]
                task.name = task_data["name"]
                task.order = task_data["order"]
                task.instructions = task_data.get("instructions", "")
                task.output_schema = task_data.get("output_schema", {})
                task.save()
            else:
                task = AgentNodeTask.objects.create(
                    agent_node=node,
                    name=task_data["name"],
                    order=task_data["order"],
                    instructions=task_data.get("instructions", ""),
                    output_schema=task_data.get("output_schema", {}),
                )

            temp_id = task_data.get("temp_id")
            if temp_id:
                temp_id_to_task_id[temp_id] = task.id

            saved_tasks.append(
                (
                    task,
                    task_data.get("context_task_temp_ids", []),
                    task_data.get("context_task_ids", []),
                )
            )

        for task, context_temp_ids, context_task_ids in saved_tasks:
            resolved_ids = set(context_task_ids)
            resolved_ids.update(
                temp_id_to_task_id[temp_id] for temp_id in context_temp_ids
            )
            task.context_tasks.set(resolved_ids)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["tasks"] = AgentNodeTaskReadSerializer(
            instance.tasks.all(), many=True
        ).data
        inline = getattr(instance, "inline_surface", None)
        data["inline_surface"] = (
            AgentInlineSurfaceReadSerializer(inline).data if inline else None
        )
        return data


class AgentNodeTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentNodeTask
        fields = [
            "id",
            "agent_node",
            "name",
            "order",
            "instructions",
            "output_schema",
            "context_tasks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_output_schema(self, value):
        return validate_output_schema(value)

    def validate(self, attrs):
        agent_node = attrs.get("agent_node") or (
            self.instance and self.instance.agent_node
        )
        order = attrs.get("order")

        if order is None and self.instance:
            order = self.instance.order

        context_tasks = attrs.get("context_tasks", [])

        for ct in context_tasks:
            if ct.agent_node_id != agent_node.id:
                raise serializers.ValidationError(
                    {
                        "context_tasks": "All referenced tasks must belong to the same agent_node."
                    }
                )

            if order is not None and ct.order >= order:
                raise serializers.ValidationError(
                    {
                        "context_tasks": "Each context task must have a strictly lower `order` than this task."
                    }
                )

        return attrs


class SubGraphNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    # Org isolation: the referenced sub-flow must be in the caller's active org.
    subgraph = OrgScopedPrimaryKeyRelatedField(
        queryset=Graph.objects.all(), required=False, allow_null=True
    )
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = SubGraphNode
        fields = "__all__"

    def validate(self, attrs):
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        subgraph = attrs.get("subgraph") or getattr(self.instance, "subgraph", None)

        if graph and subgraph and graph == subgraph:
            raise serializers.ValidationError("Graph and subgraph cannot be the same.")

        return attrs

    def to_representation(self, instance):
        from tables.serializers.model_serializers.graph_serializers import (
            GraphLightSerializer,
        )

        data = super().to_representation(instance)
        data["subgraph_detail"] = GraphLightSerializer(instance.subgraph).data
        return data
