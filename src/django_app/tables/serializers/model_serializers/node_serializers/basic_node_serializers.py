from django.db import transaction
from rest_framework import serializers

from tables.serializers.model_serializers.python_serializers import PythonCodeSerializer
from tables.models.crew_models import Crew
from tables.serializers.model_serializers.crew_serializers import (
    CrewSerializer,
)
from tables.models.graph_models import (
    AgentNode,
    AgentNodeTask,
    AudioTranscriptionNode,
    CodeAgentNode,
    CrewNode,
    Edge,
    FileExtractorNode,
    PythonNode,
    SubGraphNode,
    TaskNode,
)
from tables.serializers.base_serializer import (
    BaseGraphEntityMixin,
    ContentHashWritableMixin,
)
from tables.serializers.model_serializers.inline_surface_serializers import (
    InlineSurfaceReadSerializer,
    InlineSurfaceWriteSerializer,
)
from tables.serializers.utils.mixins import NestedPythonCodeMixin
from tables.services.inline_surface_service import InlineSurfaceService
from tables.validators.surface_validator import SurfaceValidator


class CrewNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    crew = CrewSerializer(read_only=True)
    crew_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = CrewNode
        fields = "__all__"
        read_only_fields = ["crew"]

    def validate_crew_id(self, value):
        if not Crew.objects.only("id").filter(id=value).exists():
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

    class Meta:
        model = PythonNode
        fields = "__all__"


class FileExtractorNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    class Meta:
        model = FileExtractorNode
        fields = "__all__"


class AudioTranscriptionNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    class Meta:
        model = AudioTranscriptionNode
        fields = "__all__"


class CodeAgentNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeAgentNode
        fields = "__all__"


class EdgeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    class Meta(BaseGraphEntityMixin.Meta):
        model = Edge
        fields = "__all__"


class TaskNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    inline_surface = InlineSurfaceWriteSerializer(
        required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = TaskNode
        fields = "__all__"

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


class AgentNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    class Meta:
        model = AgentNode
        fields = "__all__"


class AgentNodeTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentNodeTask
        fields = [
            "id",
            "agent_node",
            "order",
            "instructions",
            "output_schema",
            "context_tasks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

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
