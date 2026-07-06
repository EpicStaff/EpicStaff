from __future__ import annotations

from rest_framework import serializers

from tables.exceptions import SurfaceValidationError
from tables.models.agent_models.surface_models import (
    AgentInlineSurface,
    AgentInlineSurfaceGraphBasicSearchConfig,
    AgentInlineSurfaceGraphLocalSearchConfig,
    AgentInlineSurfaceKnowledge,
    AgentInlineSurfaceMcpTool,
    AgentInlineSurfaceNaiveSearchConfig,
    AgentInlineSurfacePythonTool,
    AgentInlineSurfaceStorageItem,
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

        try:
            SurfaceValidator.validate_python_tools(attrs.get("python_tools", []))
            SurfaceValidator.validate_mcp_tools(attrs.get("mcp_tools", []))

            if organization is not None:
                SurfaceValidator.validate_storage_items(
                    attrs.get("storage_items", []), organization
                )

            SurfaceValidator.validate_knowledge(attrs.get("knowledge", []))
        except SurfaceValidationError as exc:
            raise SurfaceValidationError(detail={"inline_surface": exc.detail})

        return attrs


class AgentInlineSurfacePythonToolReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentInlineSurfacePythonTool
        fields = ["python_tool", "mode"]


class AgentInlineSurfaceMcpToolReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentInlineSurfaceMcpTool
        fields = ["mcp_tool", "mode"]


class AgentInlineSurfaceStorageItemReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentInlineSurfaceStorageItem
        fields = ["storage_file", "can_list", "can_view", "can_edit", "can_delete"]


class AgentInlineSurfaceNaiveSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentInlineSurfaceNaiveSearchConfig
        fields = ["search_limit", "similarity_threshold"]


class AgentInlineSurfaceGraphBasicSearchConfigReadSerializer(
    serializers.ModelSerializer
):
    class Meta:
        model = AgentInlineSurfaceGraphBasicSearchConfig
        fields = ["prompt", "k", "max_context_tokens"]


class AgentInlineSurfaceGraphLocalSearchConfigReadSerializer(
    serializers.ModelSerializer
):
    class Meta:
        model = AgentInlineSurfaceGraphLocalSearchConfig
        fields = [
            "prompt",
            "text_unit_prop",
            "community_prop",
            "conversation_history_max_turns",
            "top_k_entities",
            "top_k_relationships",
            "max_context_tokens",
        ]


class AgentInlineSurfaceKnowledgeReadSerializer(serializers.ModelSerializer):
    naive_search_config = AgentInlineSurfaceNaiveSearchConfigReadSerializer(
        read_only=True
    )
    graph_basic_search_config = AgentInlineSurfaceGraphBasicSearchConfigReadSerializer(
        read_only=True
    )
    graph_local_search_config = AgentInlineSurfaceGraphLocalSearchConfigReadSerializer(
        read_only=True
    )

    class Meta:
        model = AgentInlineSurfaceKnowledge
        fields = [
            "collection",
            "naive_search_config",
            "graph_basic_search_config",
            "graph_local_search_config",
        ]


class AgentInlineSurfaceReadSerializer(serializers.ModelSerializer):
    python_tools = AgentInlineSurfacePythonToolReadSerializer(many=True, read_only=True)
    mcp_tools = AgentInlineSurfaceMcpToolReadSerializer(many=True, read_only=True)
    storage_items = AgentInlineSurfaceStorageItemReadSerializer(
        many=True, read_only=True
    )
    knowledge = AgentInlineSurfaceKnowledgeReadSerializer(many=True, read_only=True)

    class Meta:
        model = AgentInlineSurface
        fields = [
            "id",
            "instructions",
            "python_tools",
            "mcp_tools",
            "storage_items",
            "knowledge",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AgentInlineSurfaceWriteSerializer(serializers.Serializer):
    instructions = serializers.CharField(required=False, default="", allow_blank=True)
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

        try:
            SurfaceValidator.validate_python_tools(attrs.get("python_tools", []))
            SurfaceValidator.validate_mcp_tools(attrs.get("mcp_tools", []))

            if organization is not None:
                SurfaceValidator.validate_storage_items(
                    attrs.get("storage_items", []), organization
                )

            SurfaceValidator.validate_knowledge(attrs.get("knowledge", []))
        except SurfaceValidationError as exc:
            raise SurfaceValidationError(detail={"inline_surface": exc.detail})

        return attrs
