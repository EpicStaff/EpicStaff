from __future__ import annotations

from rest_framework import serializers

from tables.models.agent_models.surface_models import (
    Surface,
    SurfaceGraphBasicSearchConfig,
    SurfaceGraphLocalSearchConfig,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfaceNaiveSearchConfig,
    SurfacePythonTool,
    SurfaceStorageItem,
    ToolMode,
)
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool
from tables.models.graph_models import StorageFile
from tables.services.surface_service import SurfaceService
from tables.validators.surface_validator import SurfaceValidator


class SurfacePythonToolReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfacePythonTool
        fields = ["python_tool", "mode"]


class SurfaceMcpToolReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceMcpTool
        fields = ["mcp_tool", "mode"]


class SurfaceStorageItemReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceStorageItem
        fields = ["storage_file", "can_list", "can_view", "can_edit", "can_delete"]


class SurfaceNaiveSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceNaiveSearchConfig
        fields = ["search_limit", "similarity_threshold"]


class SurfaceGraphBasicSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceGraphBasicSearchConfig
        fields = ["prompt", "k", "max_context_tokens"]


class SurfaceGraphLocalSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceGraphLocalSearchConfig
        fields = [
            "prompt",
            "text_unit_prop",
            "community_prop",
            "conversation_history_max_turns",
            "top_k_entities",
            "top_k_relationships",
            "max_context_tokens",
        ]


class SurfaceKnowledgeReadSerializer(serializers.ModelSerializer):
    naive_search_config = SurfaceNaiveSearchConfigReadSerializer(read_only=True)
    graph_basic_search_config = SurfaceGraphBasicSearchConfigReadSerializer(
        read_only=True
    )
    graph_local_search_config = SurfaceGraphLocalSearchConfigReadSerializer(
        read_only=True
    )

    class Meta:
        model = SurfaceKnowledge
        fields = [
            "collection",
            "naive_search_config",
            "graph_basic_search_config",
            "graph_local_search_config",
        ]


class SurfacePythonToolWriteSerializer(serializers.Serializer):
    python_tool = serializers.PrimaryKeyRelatedField(
        queryset=PythonCodeTool.objects.all()
    )
    mode = serializers.ChoiceField(choices=ToolMode.choices)


class SurfaceMcpToolWriteSerializer(serializers.Serializer):
    mcp_tool = serializers.PrimaryKeyRelatedField(queryset=McpTool.objects.all())
    mode = serializers.ChoiceField(choices=ToolMode.choices)


class SurfaceStorageItemWriteSerializer(serializers.Serializer):
    storage_file = serializers.PrimaryKeyRelatedField(
        queryset=StorageFile.objects.all()
    )
    can_list = serializers.BooleanField(default=False)
    can_view = serializers.BooleanField(default=False)
    can_edit = serializers.BooleanField(default=False)
    can_delete = serializers.BooleanField(default=False)


class SurfaceNaiveSearchConfigWriteSerializer(serializers.Serializer):
    search_limit = serializers.IntegerField(default=3, min_value=0, max_value=1000)
    similarity_threshold = serializers.DecimalField(
        default="0.20", max_digits=3, decimal_places=2, min_value=0, max_value=1
    )


class SurfaceGraphBasicSearchConfigWriteSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    k = serializers.IntegerField(default=10)
    max_context_tokens = serializers.IntegerField(default=12000)


class SurfaceGraphLocalSearchConfigWriteSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    text_unit_prop = serializers.FloatField(default=0.5)
    community_prop = serializers.FloatField(default=0.15)
    conversation_history_max_turns = serializers.IntegerField(default=5)
    top_k_entities = serializers.IntegerField(default=10)
    top_k_relationships = serializers.IntegerField(default=10)
    max_context_tokens = serializers.IntegerField(default=12000)


class SurfaceKnowledgeWriteSerializer(serializers.Serializer):
    collection = serializers.PrimaryKeyRelatedField(
        queryset=SourceCollection.objects.all()
    )
    naive_search_config = SurfaceNaiveSearchConfigWriteSerializer(
        required=False, allow_null=True, default=None
    )
    graph_basic_search_config = SurfaceGraphBasicSearchConfigWriteSerializer(
        required=False, allow_null=True, default=None
    )
    graph_local_search_config = SurfaceGraphLocalSearchConfigWriteSerializer(
        required=False, allow_null=True, default=None
    )


class SurfaceReadSerializer(serializers.ModelSerializer):
    python_tools = SurfacePythonToolReadSerializer(many=True, read_only=True)
    mcp_tools = SurfaceMcpToolReadSerializer(many=True, read_only=True)
    storage_items = SurfaceStorageItemReadSerializer(many=True, read_only=True)
    knowledge = SurfaceKnowledgeReadSerializer(many=True, read_only=True)

    class Meta:
        model = Surface
        fields = [
            "id",
            "organization",
            "name",
            "description",
            "instructions",
            "owner_agent",
            "allow_creation",
            "python_tools",
            "mcp_tools",
            "storage_items",
            "knowledge",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SurfaceWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, default="", allow_blank=True)
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from tables.models.agent_models.agent_models import AgentDefinition

        self.fields["owner_agent"] = serializers.PrimaryKeyRelatedField(
            queryset=AgentDefinition.objects.all(),
            required=False,
            allow_null=True,
            default=None,
        )

    def validate(self, attrs):
        organization = self.context["organization"]

        SurfaceService.validate_surface_data(
            instance=self.instance,
            organization=organization,
            attrs=attrs,
        )
        SurfaceValidator.validate_python_tools(attrs.get("python_tools", []))
        SurfaceValidator.validate_mcp_tools(attrs.get("mcp_tools", []))
        SurfaceValidator.validate_storage_items(
            attrs.get("storage_items", []), organization
        )
        SurfaceValidator.validate_knowledge(attrs.get("knowledge", []))

        return attrs

    def create(self, validated_data):
        organization = self.context["organization"]
        return SurfaceService.create_surface(
            organization=organization,
            validated_data=validated_data,
        )

    def update(self, instance, validated_data):
        partial = self.context.get("partial", False)
        return SurfaceService.update_surface(
            instance=instance,
            validated_data=validated_data,
            partial=partial,
        )


class SurfacePatchWriteSerializer(SurfaceWriteSerializer):
    name = serializers.CharField(max_length=255, required=False)
    python_tools = SurfacePythonToolWriteSerializer(many=True, required=False)
    mcp_tools = SurfaceMcpToolWriteSerializer(many=True, required=False)
    storage_items = SurfaceStorageItemWriteSerializer(many=True, required=False)
    knowledge = SurfaceKnowledgeWriteSerializer(many=True, required=False)
