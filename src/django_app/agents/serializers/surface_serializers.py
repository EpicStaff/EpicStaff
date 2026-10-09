from __future__ import annotations

from rbac.scoping.fields import (
    OrganizationScopedPrimaryKeyRelatedField,
    OrgScopedPrimaryKeyRelatedField,
    OrgVisiblePrimaryKeyRelatedField,
)
from rest_framework import serializers
from tables.constants.knowledge_constants import (
    COMMUNITY_LEVEL_MAX,
    COMMUNITY_LEVEL_MIN,
    CONVERSATION_HISTORY_MAX_TURNS_MAX,
    CONVERSATION_HISTORY_MAX_TURNS_MIN,
    DRIFT_CONCURRENCY_MAX,
    DRIFT_CONCURRENCY_MIN,
    DRIFT_K_FOLLOWUPS_MAX,
    DRIFT_K_FOLLOWUPS_MIN,
    DRIFT_N_DEPTH_MAX,
    DRIFT_N_DEPTH_MIN,
    DYNAMIC_SEARCH_NUM_REPEATS_MAX,
    DYNAMIC_SEARCH_NUM_REPEATS_MIN,
    DYNAMIC_SEARCH_THRESHOLD_MAX,
    DYNAMIC_SEARCH_THRESHOLD_MIN,
    LOCAL_SEARCH_N_MAX,
    LOCAL_SEARCH_N_MIN,
    MAX_TOKEN_FIELD_VALUE,
    MIN_OPTIONAL_TOKEN_FIELD_VALUE,
    MIN_TOKEN_FIELD_VALUE,
    PRIMER_FOLDS_MAX,
    PRIMER_FOLDS_MIN,
    PROPORTION_MAX,
    PROPORTION_MIN,
    RESPONSE_MAX_LENGTH_MAX,
    RESPONSE_MAX_LENGTH_MIN,
    SEARCH_LIMIT_MAX,
    SEARCH_LIMIT_MIN,
    SEARCH_PROMPT_MAX_LENGTH,
    SIMILARITY_THRESHOLD_MAX,
    SIMILARITY_THRESHOLD_MIN,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    TOP_K_MAX,
    TOP_K_MIN,
    TOP_P_MAX,
    TOP_P_MIN,
)
from tables.models.graph_models import StorageFile
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool
from tables.validators.finite_number_validator import validate_finite_number
from tables.validators.search_config_validator import validate_proportion_sum

from agents.models.surface_models import (
    StorageAccess,
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
    ToolMode,
)
from agents.services.surface_service import SurfaceService
from agents.validators.surface_validator import SurfaceValidator


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
    graph_basic_search_config = SurfaceGraphBasicSearchConfigReadSerializer(read_only=True)
    graph_local_search_config = SurfaceGraphLocalSearchConfigReadSerializer(read_only=True)
    graph_global_search_config = SurfaceGraphGlobalSearchConfigReadSerializer(read_only=True)
    graph_drift_search_config = SurfaceGraphDriftSearchConfigReadSerializer(read_only=True)

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
    python_tool = OrgVisiblePrimaryKeyRelatedField(queryset=PythonCodeTool.objects.all())
    mode = serializers.ChoiceField(choices=ToolMode.choices)


class SurfaceMcpToolWriteSerializer(serializers.Serializer):
    mcp_tool = OrgScopedPrimaryKeyRelatedField(queryset=McpTool.objects.all())
    mode = serializers.ChoiceField(choices=ToolMode.choices)


class SurfaceStorageItemWriteSerializer(serializers.Serializer):
    storage_file = OrgScopedPrimaryKeyRelatedField(queryset=StorageFile.objects.all())
    can_list = serializers.ChoiceField(choices=StorageAccess.choices, default=StorageAccess.UNSET)
    can_view = serializers.ChoiceField(choices=StorageAccess.choices, default=StorageAccess.UNSET)
    can_edit = serializers.ChoiceField(choices=StorageAccess.choices, default=StorageAccess.UNSET)
    can_delete = serializers.ChoiceField(choices=StorageAccess.choices, default=StorageAccess.UNSET)


class SurfaceNaiveSearchConfigWriteSerializer(serializers.Serializer):
    search_limit = serializers.IntegerField(
        default=3, min_value=SEARCH_LIMIT_MIN, max_value=SEARCH_LIMIT_MAX
    )
    similarity_threshold = serializers.DecimalField(
        default="0.20",
        max_digits=3,
        decimal_places=2,
        min_value=SIMILARITY_THRESHOLD_MIN,
        max_value=SIMILARITY_THRESHOLD_MAX,
    )
    is_suggested = serializers.BooleanField(default=False)


def _prompt_field():
    return serializers.CharField(
        required=False, allow_null=True, default=None, max_length=SEARCH_PROMPT_MAX_LENGTH
    )


def _token_field(default):
    return serializers.IntegerField(
        default=default, min_value=MIN_TOKEN_FIELD_VALUE, max_value=MAX_TOKEN_FIELD_VALUE
    )


def _optional_token_field():
    return serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        min_value=MIN_OPTIONAL_TOKEN_FIELD_VALUE,
        max_value=MAX_TOKEN_FIELD_VALUE,
    )


def _top_k_field(default):
    return serializers.IntegerField(default=default, min_value=TOP_K_MIN, max_value=TOP_K_MAX)


def _proportion_field(default):
    return serializers.FloatField(
        default=default,
        min_value=PROPORTION_MIN,
        max_value=PROPORTION_MAX,
        validators=[validate_finite_number],
    )


def _validate_proportion_sum_with_defaults(serializer, attrs, first_field, second_field):
    # A PATCH (partial root) skips field defaults, yet an omitted proportion is stored
    # with its default, so the sum must be checked against that default.
    values = {
        field_name: attrs.get(field_name, serializer.fields[field_name].default)
        for field_name in (first_field, second_field)
    }
    validate_proportion_sum(values, first_field, second_field)


def _temperature_field():
    return serializers.FloatField(
        default=0.0,
        min_value=TEMPERATURE_MIN,
        max_value=TEMPERATURE_MAX,
        validators=[validate_finite_number],
    )


class SurfaceGraphBasicSearchConfigWriteSerializer(serializers.Serializer):
    prompt = _prompt_field()
    k = _top_k_field(10)
    max_context_tokens = _token_field(12000)
    is_suggested = serializers.BooleanField(default=False)


class SurfaceGraphLocalSearchConfigWriteSerializer(serializers.Serializer):
    prompt = _prompt_field()
    text_unit_prop = _proportion_field(0.5)
    community_prop = _proportion_field(0.15)
    conversation_history_max_turns = serializers.IntegerField(
        default=5,
        min_value=CONVERSATION_HISTORY_MAX_TURNS_MIN,
        max_value=CONVERSATION_HISTORY_MAX_TURNS_MAX,
    )
    top_k_entities = _top_k_field(10)
    top_k_relationships = _top_k_field(10)
    max_context_tokens = _token_field(12000)
    is_suggested = serializers.BooleanField(default=False)

    def validate(self, attrs):
        _validate_proportion_sum_with_defaults(self, attrs, "text_unit_prop", "community_prop")
        return attrs


class SurfaceGraphGlobalSearchConfigWriteSerializer(serializers.Serializer):
    map_prompt = _prompt_field()
    reduce_prompt = _prompt_field()
    knowledge_prompt = _prompt_field()
    max_context_tokens = _token_field(12000)
    data_max_tokens = _token_field(12000)
    map_max_length = serializers.IntegerField(
        default=1000, min_value=RESPONSE_MAX_LENGTH_MIN, max_value=RESPONSE_MAX_LENGTH_MAX
    )
    reduce_max_length = serializers.IntegerField(
        default=2000, min_value=RESPONSE_MAX_LENGTH_MIN, max_value=RESPONSE_MAX_LENGTH_MAX
    )
    dynamic_community_selection = serializers.BooleanField(default=False)
    dynamic_search_threshold = serializers.IntegerField(
        default=1,
        min_value=DYNAMIC_SEARCH_THRESHOLD_MIN,
        max_value=DYNAMIC_SEARCH_THRESHOLD_MAX,
    )
    dynamic_search_keep_parent = serializers.BooleanField(default=False)
    dynamic_search_num_repeats = serializers.IntegerField(
        default=1,
        min_value=DYNAMIC_SEARCH_NUM_REPEATS_MIN,
        max_value=DYNAMIC_SEARCH_NUM_REPEATS_MAX,
    )
    dynamic_search_use_summary = serializers.BooleanField(default=False)
    dynamic_search_max_level = serializers.IntegerField(
        default=2, min_value=COMMUNITY_LEVEL_MIN, max_value=COMMUNITY_LEVEL_MAX
    )
    is_suggested = serializers.BooleanField(default=False)


class SurfaceGraphDriftSearchConfigWriteSerializer(serializers.Serializer):
    prompt = _prompt_field()
    reduce_prompt = _prompt_field()
    data_max_tokens = _token_field(12000)
    reduce_max_tokens = _optional_token_field()
    reduce_temperature = _temperature_field()
    reduce_max_completion_tokens = _optional_token_field()
    concurrency = serializers.IntegerField(
        default=32, min_value=DRIFT_CONCURRENCY_MIN, max_value=DRIFT_CONCURRENCY_MAX
    )
    drift_k_followups = serializers.IntegerField(
        default=20, min_value=DRIFT_K_FOLLOWUPS_MIN, max_value=DRIFT_K_FOLLOWUPS_MAX
    )
    primer_folds = serializers.IntegerField(
        default=5, min_value=PRIMER_FOLDS_MIN, max_value=PRIMER_FOLDS_MAX
    )
    primer_llm_max_tokens = _token_field(12000)
    n_depth = serializers.IntegerField(
        default=3, min_value=DRIFT_N_DEPTH_MIN, max_value=DRIFT_N_DEPTH_MAX
    )
    community_level = serializers.IntegerField(
        default=2, min_value=COMMUNITY_LEVEL_MIN, max_value=COMMUNITY_LEVEL_MAX
    )
    local_search_text_unit_prop = _proportion_field(0.9)
    local_search_community_prop = _proportion_field(0.1)
    local_search_top_k_mapped_entities = _top_k_field(10)
    local_search_top_k_relationships = _top_k_field(10)
    local_search_max_data_tokens = _token_field(12000)
    local_search_temperature = _temperature_field()
    local_search_top_p = serializers.FloatField(
        default=1.0, min_value=TOP_P_MIN, max_value=TOP_P_MAX, validators=[validate_finite_number]
    )
    local_search_n = serializers.IntegerField(
        default=1, min_value=LOCAL_SEARCH_N_MIN, max_value=LOCAL_SEARCH_N_MAX
    )
    local_search_llm_max_gen_tokens = _optional_token_field()
    local_search_llm_max_gen_completion_tokens = _optional_token_field()
    is_suggested = serializers.BooleanField(default=False)

    def validate(self, attrs):
        _validate_proportion_sum_with_defaults(
            self, attrs, "local_search_text_unit_prop", "local_search_community_prop"
        )
        return attrs


class SurfaceKnowledgeWriteSerializer(serializers.Serializer):
    collection = OrgScopedPrimaryKeyRelatedField(queryset=SourceCollection.objects.all())
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
    python_tools = SurfacePythonToolWriteSerializer(many=True, required=False, default=list)
    mcp_tools = SurfaceMcpToolWriteSerializer(many=True, required=False, default=list)
    storage_items = SurfaceStorageItemWriteSerializer(many=True, required=False, default=list)
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
        organization_id = self.context["organization_id"]

        SurfaceService.validate_surface_data(
            instance=self.instance,
            organization_id=organization_id,
            attrs=attrs,
        )
        SurfaceValidator.validate_python_tools(attrs.get("python_tools", []))
        SurfaceValidator.validate_mcp_tools(attrs.get("mcp_tools", []))
        SurfaceValidator.validate_storage_items(attrs.get("storage_items", []))
        SurfaceValidator.validate_knowledge(attrs.get("knowledge", []))

        return attrs

    def create(self, validated_data):
        organization_id = self.context["organization_id"]
        return SurfaceService.create_surface(
            organization_id=organization_id,
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
        organization_id = self.context.get("organization_id")

        if organization_id is not None:
            self.fields["surface_ids"].child_relation.queryset = Surface.objects.filter(
                organization_id=organization_id
            )

    def validate_surface_ids(self, value):
        if len(value) != len({s.pk for s in value}):
            raise serializers.ValidationError("Duplicate surface ids are not allowed.")

        return value
