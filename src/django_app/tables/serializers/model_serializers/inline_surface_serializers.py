from __future__ import annotations

from rest_framework import serializers

from tables.models.agent_models.surface_models import (
    InlineSurface,
    InlineSurfaceGraphBasicSearchConfig,
    InlineSurfaceGraphLocalSearchConfig,
    InlineSurfaceKnowledge,
    InlineSurfaceMcpTool,
    InlineSurfaceNaiveSearchConfig,
    InlineSurfacePythonTool,
    InlineSurfaceStorageItem,
)
from tables.serializers.model_serializers.surface_serializers import (
    SurfaceKnowledgeWriteSerializer,
    SurfaceMcpToolWriteSerializer,
    SurfacePythonToolWriteSerializer,
    SurfaceStorageItemWriteSerializer,
)
from tables.validators.surface_validator import SurfaceValidator


class InlineSurfacePythonToolReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InlineSurfacePythonTool
        fields = ["python_tool", "mode"]


class InlineSurfaceMcpToolReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InlineSurfaceMcpTool
        fields = ["mcp_tool", "mode"]


class InlineSurfaceStorageItemReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InlineSurfaceStorageItem
        fields = ["storage_file", "can_list", "can_view", "can_edit", "can_delete"]


class InlineSurfaceNaiveSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InlineSurfaceNaiveSearchConfig
        fields = ["search_limit", "similarity_threshold"]


class InlineSurfaceGraphBasicSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InlineSurfaceGraphBasicSearchConfig
        fields = ["prompt", "k", "max_context_tokens"]


class InlineSurfaceGraphLocalSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InlineSurfaceGraphLocalSearchConfig
        fields = [
            "prompt",
            "text_unit_prop",
            "community_prop",
            "conversation_history_max_turns",
            "top_k_entities",
            "top_k_relationships",
            "max_context_tokens",
        ]


class InlineSurfaceKnowledgeReadSerializer(serializers.ModelSerializer):
    naive_search_config = InlineSurfaceNaiveSearchConfigReadSerializer(read_only=True)
    graph_basic_search_config = InlineSurfaceGraphBasicSearchConfigReadSerializer(
        read_only=True
    )
    graph_local_search_config = InlineSurfaceGraphLocalSearchConfigReadSerializer(
        read_only=True
    )

    class Meta:
        model = InlineSurfaceKnowledge
        fields = [
            "collection",
            "naive_search_config",
            "graph_basic_search_config",
            "graph_local_search_config",
        ]


class InlineSurfaceReadSerializer(serializers.ModelSerializer):
    python_tools = InlineSurfacePythonToolReadSerializer(many=True, read_only=True)
    mcp_tools = InlineSurfaceMcpToolReadSerializer(many=True, read_only=True)
    storage_items = InlineSurfaceStorageItemReadSerializer(many=True, read_only=True)
    knowledge = InlineSurfaceKnowledgeReadSerializer(many=True, read_only=True)

    class Meta:
        model = InlineSurface
        fields = [
            "id",
            "instructions",
            "allow_creation",
            "python_tools",
            "mcp_tools",
            "storage_items",
            "knowledge",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class InlineSurfaceWriteSerializer(serializers.Serializer):
    instructions = serializers.CharField(required=False, default="", allow_blank=True)
    allow_creation = serializers.BooleanField(required=False, default=False)
    python_tools = SurfacePythonToolWriteSerializer(
        many=True, required=False, default=list
    )
    mcp_tools = SurfaceMcpToolWriteSerializer(many=True, required=False, default=list)
    storage_items = SurfaceStorageItemWriteSerializer(
        many=True, required=False, default=list
    )
    knowledge = SurfaceKnowledgeWriteSerializer(many=True, required=False, default=list)

    def validate(self, attrs):
        organization = self.context.get("organization")

        SurfaceValidator.validate_python_tools(attrs.get("python_tools", []))
        SurfaceValidator.validate_mcp_tools(attrs.get("mcp_tools", []))

        if organization is not None:
            SurfaceValidator.validate_storage_items(
                attrs.get("storage_items", []), organization
            )

        SurfaceValidator.validate_knowledge(attrs.get("knowledge", []))

        return attrs
