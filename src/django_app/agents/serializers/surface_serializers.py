from __future__ import annotations

from rest_framework import serializers

from agents.models.surface_models import (
    Surface,
    SurfaceGraphBasicSearchConfig,
    SurfaceGraphDriftSearchConfig,
    SurfaceGraphGlobalSearchConfig,
    SurfaceGraphLocalSearchConfig,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfaceNaiveSearchConfig,
    SurfacePythonTool,
    SurfaceStorageItem,
    StorageAccess,
    ToolMode,
)
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool
from tables.models.graph_models import StorageFile
from agents.services.surface_service import SurfaceService
from agents.validators.surface_validator import SurfaceValidator
from tables.serializers.org_scoped_fields import (
    OrganizationScopedPrimaryKeyRelatedField,
    OrgScopedPrimaryKeyRelatedField,
    OrgVisiblePrimaryKeyRelatedField,
)


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
        fields = ["search_limit", "similarity_threshold", "is_suggested"]


class SurfaceGraphBasicSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceGraphBasicSearchConfig
        fields = ["prompt", "k", "max_context_tokens", "is_suggested"]


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
            "is_suggested",
        ]


class SurfaceGraphGlobalSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceGraphGlobalSearchConfig
        fields = [
            "map_prompt",
            "reduce_prompt",
            "knowledge_prompt",
            "max_context_tokens",
            "data_max_tokens",
            "map_max_length",
            "reduce_max_length",
            "dynamic_community_selection",
            "dynamic_search_threshold",
            "dynamic_search_keep_parent",
            "dynamic_search_num_repeats",
            "dynamic_search_use_summary",
            "dynamic_search_max_level",
            "is_suggested",
        ]


class SurfaceGraphDriftSearchConfigReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurfaceGraphDriftSearchConfig
        fields = [
            "prompt",
            "reduce_prompt",
            "data_max_tokens",
            "reduce_max_tokens",
            "reduce_temperature",
            "reduce_max_completion_tokens",
            "concurrency",
            "drift_k_followups",
            "primer_folds",
            "primer_llm_max_tokens",
            "n_depth",
            "community_level",
            "local_search_text_unit_prop",
            "local_search_community_prop",
            "local_search_top_k_mapped_entities",
            "local_search_top_k_relationships",
            "local_search_max_data_tokens",
            "local_search_temperature",
            "local_search_top_p",
            "local_search_n",
            "local_search_llm_max_gen_tokens",
            "local_search_llm_max_gen_completion_tokens",
            "is_suggested",
        ]


class SurfaceKnowledgeReadSerializer(serializers.ModelSerializer):
    naive_search_config = SurfaceNaiveSearchConfigReadSerializer(read_only=True)
    graph_basic_search_config = SurfaceGraphBasicSearchConfigReadSerializer(
        read_only=True
    )
    graph_local_search_config = SurfaceGraphLocalSearchConfigReadSerializer(
        read_only=True
    )
    graph_global_search_config = SurfaceGraphGlobalSearchConfigReadSerializer(
        read_only=True
    )
    graph_drift_search_config = SurfaceGraphDriftSearchConfigReadSerializer(
        read_only=True
    )

    class Meta:
        model = SurfaceKnowledge
        fields = [
            "collection",
            "naive_search_config",
            "graph_basic_search_config",
            "graph_local_search_config",
            "graph_global_search_config",
            "graph_drift_search_config",
        ]


class SurfacePythonToolWriteSerializer(serializers.Serializer):
    python_tool = OrgVisiblePrimaryKeyRelatedField(
        queryset=PythonCodeTool.objects.all()
    )
    mode = serializers.ChoiceField(choices=ToolMode.choices)


class SurfaceMcpToolWriteSerializer(serializers.Serializer):
    mcp_tool = OrgScopedPrimaryKeyRelatedField(queryset=McpTool.objects.all())
    mode = serializers.ChoiceField(choices=ToolMode.choices)


class SurfaceStorageItemWriteSerializer(serializers.Serializer):
    storage_file = OrgScopedPrimaryKeyRelatedField(queryset=StorageFile.objects.all())
    can_list = serializers.ChoiceField(
        choices=StorageAccess.choices, default=StorageAccess.UNSET
    )
    can_view = serializers.ChoiceField(
        choices=StorageAccess.choices, default=StorageAccess.UNSET
    )
    can_edit = serializers.ChoiceField(
        choices=StorageAccess.choices, default=StorageAccess.UNSET
    )
    can_delete = serializers.ChoiceField(
        choices=StorageAccess.choices, default=StorageAccess.UNSET
    )


class SurfaceNaiveSearchConfigWriteSerializer(serializers.Serializer):
    search_limit = serializers.IntegerField(default=3, min_value=0, max_value=1000)
    similarity_threshold = serializers.DecimalField(
        default="0.20", max_digits=3, decimal_places=2, min_value=0, max_value=1
    )
    is_suggested = serializers.BooleanField(default=False)


class SurfaceGraphBasicSearchConfigWriteSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    k = serializers.IntegerField(default=10)
    max_context_tokens = serializers.IntegerField(default=12000)
    is_suggested = serializers.BooleanField(default=False)


class SurfaceGraphLocalSearchConfigWriteSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    text_unit_prop = serializers.FloatField(default=0.5)
    community_prop = serializers.FloatField(default=0.15)
    conversation_history_max_turns = serializers.IntegerField(default=5)
    top_k_entities = serializers.IntegerField(default=10)
    top_k_relationships = serializers.IntegerField(default=10)
    max_context_tokens = serializers.IntegerField(default=12000)
    is_suggested = serializers.BooleanField(default=False)


class SurfaceGraphGlobalSearchConfigWriteSerializer(serializers.Serializer):
    map_prompt = serializers.CharField(required=False, allow_null=True, default=None)
    reduce_prompt = serializers.CharField(required=False, allow_null=True, default=None)
    knowledge_prompt = serializers.CharField(
        required=False, allow_null=True, default=None
    )
    max_context_tokens = serializers.IntegerField(default=12000)
    data_max_tokens = serializers.IntegerField(default=12000)
    map_max_length = serializers.IntegerField(default=1000)
    reduce_max_length = serializers.IntegerField(default=2000)
    dynamic_community_selection = serializers.BooleanField(default=False)
    dynamic_search_threshold = serializers.IntegerField(default=1)
    dynamic_search_keep_parent = serializers.BooleanField(default=False)
    dynamic_search_num_repeats = serializers.IntegerField(default=1)
    dynamic_search_use_summary = serializers.BooleanField(default=False)
    dynamic_search_max_level = serializers.IntegerField(default=2)
    is_suggested = serializers.BooleanField(default=False)


class SurfaceGraphDriftSearchConfigWriteSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=False, allow_null=True, default=None)
    reduce_prompt = serializers.CharField(required=False, allow_null=True, default=None)
    data_max_tokens = serializers.IntegerField(default=12000)
    reduce_max_tokens = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    reduce_temperature = serializers.FloatField(default=0.0)
    reduce_max_completion_tokens = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    concurrency = serializers.IntegerField(default=32)
    drift_k_followups = serializers.IntegerField(default=20)
    primer_folds = serializers.IntegerField(default=5)
    primer_llm_max_tokens = serializers.IntegerField(default=12000)
    n_depth = serializers.IntegerField(default=3)
    community_level = serializers.IntegerField(default=2)
    local_search_text_unit_prop = serializers.FloatField(default=0.9)
    local_search_community_prop = serializers.FloatField(default=0.1)
    local_search_top_k_mapped_entities = serializers.IntegerField(default=10)
    local_search_top_k_relationships = serializers.IntegerField(default=10)
    local_search_max_data_tokens = serializers.IntegerField(default=12000)
    local_search_temperature = serializers.FloatField(default=0.0)
    local_search_top_p = serializers.FloatField(default=1.0)
    local_search_n = serializers.IntegerField(default=1)
    local_search_llm_max_gen_tokens = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    local_search_llm_max_gen_completion_tokens = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    is_suggested = serializers.BooleanField(default=False)


class SurfaceKnowledgeWriteSerializer(serializers.Serializer):
    collection = OrgScopedPrimaryKeyRelatedField(
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
    graph_global_search_config = SurfaceGraphGlobalSearchConfigWriteSerializer(
        required=False, allow_null=True, default=None
    )
    graph_drift_search_config = SurfaceGraphDriftSearchConfigWriteSerializer(
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
            "instructions",
            "owner_agent",
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
    instructions = serializers.CharField(required=False, default="", allow_blank=True)
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
        from agents.models.agent_models import AgentDefinition

        self.fields["owner_agent"] = OrganizationScopedPrimaryKeyRelatedField(
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


class SurfaceCombineRequestSerializer(serializers.Serializer):
    surface_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        allow_empty=False,
        queryset=Surface.objects.none(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.context.get("organization")

        if organization is not None:
            self.fields["surface_ids"].child_relation.queryset = Surface.objects.filter(
                organization=organization
            )

    def validate_surface_ids(self, value):
        if len(value) != len({s.pk for s in value}):
            raise serializers.ValidationError("Duplicate surface ids are not allowed.")

        return value
