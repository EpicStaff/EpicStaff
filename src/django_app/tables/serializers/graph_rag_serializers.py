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
    GRAPHRAG_MAX_CHUNK_OVERLAP,
    GRAPHRAG_MAX_CHUNK_SIZE,
    GRAPHRAG_MAX_MAX_CLUSTER_SIZE,
    GRAPHRAG_MAX_MAX_GLEANINGS,
    GRAPHRAG_MIN_CHUNK_OVERLAP,
    GRAPHRAG_MIN_CHUNK_SIZE,
    GRAPHRAG_MIN_MAX_CLUSTER_SIZE,
    GRAPHRAG_MIN_MAX_GLEANINGS,
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
    SEARCH_PROMPT_MAX_LENGTH,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    TOP_K_MAX,
    TOP_K_MIN,
    TOP_P_MAX,
    TOP_P_MIN,
)
from tables.models.knowledge_models import (
    GraphRag,
    GraphRagChunkStrategyType,
    GraphRagDocument,
    GraphRagIndexConfig,
    GraphRagInputFileType,
)
from tables.serializers.knowledge_serializers import BaseRagTypeSerializer
from tables.validators.finite_number_validator import validate_finite_number
from tables.validators.search_config_validator import validate_proportion_sum


class GraphRagCreateSerializer(serializers.Serializer):
    """
    Serializer for creating GraphRag.
    """

    embedder_id = serializers.IntegerField(required=True, help_text="ID of the embedder to use")
    llm_id = serializers.IntegerField(
        required=True, help_text="ID of the LLM config to use for entity extraction"
    )

    def validate_embedder_id(self, value):
        """Validate embedder_id is positive."""
        if value <= 0:
            raise serializers.ValidationError("embedder_id must be positive")
        return value

    def validate_llm_id(self, value):
        """Validate llm_id is positive."""
        if value <= 0:
            raise serializers.ValidationError("llm_id must be positive")
        return value


class GraphRagIndexConfigSerializer(serializers.ModelSerializer):
    """Serializer for GraphRagIndexConfig."""

    class Meta:
        model = GraphRagIndexConfig
        fields = [
            "id",
            # Input config
            "file_type",
            # Chunking config
            "chunk_size",
            "chunk_overlap",
            "chunk_strategy",
            # Entity extraction config
            "entity_types",
            "max_gleanings",
            # Cluster config
            "max_cluster_size",
        ]
        read_only_fields = fields


class GraphRagSerializer(serializers.ModelSerializer):
    """
    Serializer for GraphRag details.
    Used for displaying GraphRag information.
    """

    base_rag_type = BaseRagTypeSerializer(read_only=True)
    embedder_name = serializers.CharField(source="embedder.custom_name", read_only=True)
    llm_name = serializers.CharField(source="llm.custom_name", read_only=True)
    collection_id = serializers.IntegerField(
        source="base_rag_type.source_collection_id", read_only=True
    )

    class Meta:
        model = GraphRag
        fields = [
            "graph_rag_id",
            "base_rag_type",
            "embedder",
            "embedder_name",
            "llm",
            "llm_name",
            "rag_status",
            "outdated_reasons",
            "collection_id",
            "error_message",
            "created_at",
            "updated_at",
            "indexed_at",
        ]
        read_only_fields = fields


class GraphRagDocumentSerializer(serializers.ModelSerializer):
    """Serializer for GraphRagDocument."""

    document_id = serializers.IntegerField(source="document.document_id", read_only=True)
    file_name = serializers.CharField(source="document.file_name", read_only=True)
    file_type = serializers.CharField(source="document.file_type", read_only=True)
    file_size = serializers.IntegerField(source="document.file_size", read_only=True)

    class Meta:
        model = GraphRagDocument
        fields = [
            "graph_rag_document_id",
            "document_id",
            "file_name",
            "file_type",
            "file_size",
            "created_at",
        ]
        read_only_fields = fields


class GraphRagDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for GraphRag with index config and documents.
    """

    base_rag_type = BaseRagTypeSerializer(read_only=True)
    embedder_name = serializers.CharField(source="embedder.custom_name", read_only=True)
    llm_name = serializers.CharField(source="llm.custom_name", read_only=True)
    collection_id = serializers.IntegerField(
        source="base_rag_type.source_collection_id", read_only=True
    )
    collection_name = serializers.CharField(
        source="base_rag_type.source_collection.collection_name", read_only=True
    )
    index_config = GraphRagIndexConfigSerializer(read_only=True)
    total_documents_in_collection = serializers.SerializerMethodField()
    documents_in_graph_rag = serializers.SerializerMethodField()
    processing_document_ids = serializers.ListSerializer(
        source="indexing_document_config_ids",
        child=serializers.IntegerField(),
        allow_empty=True,
    )

    class Meta:
        model = GraphRag
        fields = [
            "graph_rag_id",
            "base_rag_type",
            "embedder",
            "embedder_name",
            "llm",
            "llm_name",
            "rag_status",
            "outdated_reasons",
            "collection_id",
            "collection_name",
            "processing_document_ids",
            "index_config",
            "total_documents_in_collection",
            "documents_in_graph_rag",
            "error_message",
            "created_at",
            "updated_at",
            "indexed_at",
        ]
        read_only_fields = fields

    def get_total_documents_in_collection(self, obj):
        """Get total documents in collection."""
        return obj.base_rag_type.source_collection.documents.count()

    def get_documents_in_graph_rag(self, obj):
        """Get count of documents in GraphRag."""
        return obj.graph_rag_documents.count()


class GraphRagIndexConfigUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating GraphRag index configuration.
    All fields optional - only updates provided fields.
    Updates all nested configs in one request.
    """

    # Input config
    file_type = serializers.ChoiceField(
        required=False,
        choices=GraphRagInputFileType.choices,
        help_text="Input file type (csv, text, json)",
    )

    # Chunking config
    chunk_size = serializers.IntegerField(
        required=False,
        min_value=GRAPHRAG_MIN_CHUNK_SIZE,
        max_value=GRAPHRAG_MAX_CHUNK_SIZE,
        help_text=f"Chunk size ({GRAPHRAG_MIN_CHUNK_SIZE}-{GRAPHRAG_MAX_CHUNK_SIZE})",
    )
    chunk_overlap = serializers.IntegerField(
        required=False,
        min_value=GRAPHRAG_MIN_CHUNK_OVERLAP,
        max_value=GRAPHRAG_MAX_CHUNK_OVERLAP,
        help_text=f"Chunk overlap ({GRAPHRAG_MIN_CHUNK_OVERLAP}-{GRAPHRAG_MAX_CHUNK_OVERLAP})",
    )
    chunk_strategy = serializers.ChoiceField(
        required=False,
        choices=GraphRagChunkStrategyType.choices,
        help_text="Chunking strategy (tokens, sentence)",
    )

    # Extract graph config
    entity_types = serializers.ListField(
        required=False,
        child=serializers.CharField(),
        allow_empty=False,
        help_text="List of entity types to extract",
    )
    max_gleanings = serializers.IntegerField(
        required=False,
        min_value=GRAPHRAG_MIN_MAX_GLEANINGS,
        max_value=GRAPHRAG_MAX_MAX_GLEANINGS,
        help_text=f"Maximum gleanings ({GRAPHRAG_MIN_MAX_GLEANINGS}-{GRAPHRAG_MAX_MAX_GLEANINGS})",
    )

    # Cluster graph config
    max_cluster_size = serializers.IntegerField(
        required=False,
        min_value=GRAPHRAG_MIN_MAX_CLUSTER_SIZE,
        max_value=GRAPHRAG_MAX_MAX_CLUSTER_SIZE,
        help_text=f"Maximum cluster size ({GRAPHRAG_MIN_MAX_CLUSTER_SIZE}-{GRAPHRAG_MAX_MAX_CLUSTER_SIZE})",
    )

    def validate(self, attrs):
        """Ensure at least one field is provided."""
        if not attrs:
            raise serializers.ValidationError("At least one field must be provided for update")

        chunk_size = attrs.get("chunk_size")
        chunk_overlap = attrs.get("chunk_overlap")
        if chunk_size and chunk_overlap and chunk_overlap >= chunk_size:
            raise serializers.ValidationError(
                {"chunk_overlap": ['Must be less than "chunk_size".']}
            )

        return attrs


class GraphRagDocumentIdsSerializer(serializers.Serializer):
    """
    Serializer for adding/removing documents from GraphRag.
    """

    document_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=True,
        allow_empty=False,
        help_text="List of document IDs to add/remove",
    )

    def validate_document_ids(self, value):
        """Remove duplicates."""
        return list(set(value))


class GraphRagLightSerializer(serializers.ModelSerializer):
    """Lightweight serializer for dropdown lists."""

    collection_id = serializers.IntegerField(
        source="base_rag_type.source_collection_id", read_only=True
    )

    class Meta:
        model = GraphRag
        fields = [
            "graph_rag_id",
            "rag_status",
            "collection_id",
            "created_at",
            "indexed_at",
        ]
        read_only_fields = fields


# Search Config Serializers


class GraphBasicSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for graph RAG basic search config."""

    prompt = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=SEARCH_PROMPT_MAX_LENGTH,
        help_text="Custom basic search prompt",
    )
    k = serializers.IntegerField(
        required=False,
        min_value=TOP_K_MIN,
        max_value=TOP_K_MAX,
        help_text=f"Number of text units to include ({TOP_K_MIN}-{TOP_K_MAX})",
    )
    max_context_tokens = serializers.IntegerField(
        required=False,
        min_value=MIN_TOKEN_FIELD_VALUE,
        max_value=MAX_TOKEN_FIELD_VALUE,
        help_text=f"Maximum context tokens ({MIN_TOKEN_FIELD_VALUE}-{MAX_TOKEN_FIELD_VALUE})",
    )
    is_suggested = serializers.BooleanField(
        required=False,
        help_text="Whether these values came from parameter suggestion.",
    )


class GraphLocalSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for graph RAG local search config."""

    prompt = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=SEARCH_PROMPT_MAX_LENGTH,
        help_text="Custom local search prompt",
    )
    text_unit_prop = serializers.FloatField(
        required=False,
        min_value=PROPORTION_MIN,
        max_value=PROPORTION_MAX,
        help_text="Text unit proportion (0.0-1.0)",
        validators=[validate_finite_number],
    )
    community_prop = serializers.FloatField(
        required=False,
        min_value=PROPORTION_MIN,
        max_value=PROPORTION_MAX,
        help_text="Community proportion (0.0-1.0)",
        validators=[validate_finite_number],
    )
    conversation_history_max_turns = serializers.IntegerField(
        required=False,
        min_value=CONVERSATION_HISTORY_MAX_TURNS_MIN,
        max_value=CONVERSATION_HISTORY_MAX_TURNS_MAX,
        help_text=(
            "Max conversation history turns "
            f"({CONVERSATION_HISTORY_MAX_TURNS_MIN}-{CONVERSATION_HISTORY_MAX_TURNS_MAX})"
        ),
    )
    top_k_entities = serializers.IntegerField(
        required=False,
        min_value=TOP_K_MIN,
        max_value=TOP_K_MAX,
        help_text=f"Top K entities ({TOP_K_MIN}-{TOP_K_MAX})",
    )
    top_k_relationships = serializers.IntegerField(
        required=False,
        min_value=TOP_K_MIN,
        max_value=TOP_K_MAX,
        help_text=f"Top K relationships ({TOP_K_MIN}-{TOP_K_MAX})",
    )
    max_context_tokens = serializers.IntegerField(
        required=False,
        min_value=MIN_TOKEN_FIELD_VALUE,
        max_value=MAX_TOKEN_FIELD_VALUE,
        help_text=f"Maximum context tokens ({MIN_TOKEN_FIELD_VALUE}-{MAX_TOKEN_FIELD_VALUE})",
    )
    is_suggested = serializers.BooleanField(
        required=False,
        help_text="Whether these values came from parameter suggestion.",
    )

    def validate(self, attrs):
        validate_proportion_sum(attrs, "text_unit_prop", "community_prop")
        return attrs


def _prompt_field():
    return serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=SEARCH_PROMPT_MAX_LENGTH,
    )


def _token_field():
    return serializers.IntegerField(
        required=False, min_value=MIN_TOKEN_FIELD_VALUE, max_value=MAX_TOKEN_FIELD_VALUE
    )


def _optional_token_field():
    return serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=MIN_OPTIONAL_TOKEN_FIELD_VALUE,
        max_value=MAX_TOKEN_FIELD_VALUE,
    )


def _bounded_integer_field(minimum, maximum):
    return serializers.IntegerField(required=False, min_value=minimum, max_value=maximum)


def _bounded_float_field(minimum, maximum):
    return serializers.FloatField(
        required=False,
        min_value=minimum,
        max_value=maximum,
        validators=[validate_finite_number],
    )


class GraphGlobalSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for graph RAG global search config."""

    map_prompt = _prompt_field()
    reduce_prompt = _prompt_field()
    knowledge_prompt = _prompt_field()
    max_context_tokens = _token_field()
    data_max_tokens = _token_field()
    map_max_length = _bounded_integer_field(RESPONSE_MAX_LENGTH_MIN, RESPONSE_MAX_LENGTH_MAX)
    reduce_max_length = _bounded_integer_field(RESPONSE_MAX_LENGTH_MIN, RESPONSE_MAX_LENGTH_MAX)
    dynamic_community_selection = serializers.BooleanField(required=False)
    dynamic_search_threshold = _bounded_integer_field(
        DYNAMIC_SEARCH_THRESHOLD_MIN, DYNAMIC_SEARCH_THRESHOLD_MAX
    )
    dynamic_search_keep_parent = serializers.BooleanField(required=False)
    dynamic_search_num_repeats = _bounded_integer_field(
        DYNAMIC_SEARCH_NUM_REPEATS_MIN, DYNAMIC_SEARCH_NUM_REPEATS_MAX
    )
    dynamic_search_use_summary = serializers.BooleanField(required=False)
    dynamic_search_max_level = _bounded_integer_field(COMMUNITY_LEVEL_MIN, COMMUNITY_LEVEL_MAX)
    is_suggested = serializers.BooleanField(
        required=False,
        help_text="Whether these values came from parameter suggestion.",
    )


class GraphDriftSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for graph RAG drift search config."""

    prompt = _prompt_field()
    reduce_prompt = _prompt_field()
    data_max_tokens = _token_field()
    reduce_max_tokens = _optional_token_field()
    reduce_temperature = _bounded_float_field(TEMPERATURE_MIN, TEMPERATURE_MAX)
    reduce_max_completion_tokens = _optional_token_field()
    concurrency = _bounded_integer_field(DRIFT_CONCURRENCY_MIN, DRIFT_CONCURRENCY_MAX)
    drift_k_followups = _bounded_integer_field(DRIFT_K_FOLLOWUPS_MIN, DRIFT_K_FOLLOWUPS_MAX)
    primer_folds = _bounded_integer_field(PRIMER_FOLDS_MIN, PRIMER_FOLDS_MAX)
    primer_llm_max_tokens = _token_field()
    n_depth = _bounded_integer_field(DRIFT_N_DEPTH_MIN, DRIFT_N_DEPTH_MAX)
    community_level = _bounded_integer_field(COMMUNITY_LEVEL_MIN, COMMUNITY_LEVEL_MAX)
    local_search_text_unit_prop = _bounded_float_field(PROPORTION_MIN, PROPORTION_MAX)
    local_search_community_prop = _bounded_float_field(PROPORTION_MIN, PROPORTION_MAX)
    local_search_top_k_mapped_entities = _bounded_integer_field(TOP_K_MIN, TOP_K_MAX)
    local_search_top_k_relationships = _bounded_integer_field(TOP_K_MIN, TOP_K_MAX)
    local_search_max_data_tokens = _token_field()
    local_search_temperature = _bounded_float_field(TEMPERATURE_MIN, TEMPERATURE_MAX)
    local_search_top_p = _bounded_float_field(TOP_P_MIN, TOP_P_MAX)
    local_search_n = _bounded_integer_field(LOCAL_SEARCH_N_MIN, LOCAL_SEARCH_N_MAX)
    local_search_llm_max_gen_tokens = _optional_token_field()
    local_search_llm_max_gen_completion_tokens = _optional_token_field()
    is_suggested = serializers.BooleanField(
        required=False,
        help_text="Whether these values came from parameter suggestion.",
    )

    def validate(self, attrs):
        validate_proportion_sum(attrs, "local_search_text_unit_prop", "local_search_community_prop")
        return attrs


class GraphSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for graph RAG search config wrapper."""

    search_method = serializers.ChoiceField(
        choices=["basic", "local", "global", "drift"],
        required=False,
        allow_null=True,
        help_text="Active search method",
    )
    basic = GraphBasicSearchConfigInputSerializer(
        required=False,
        help_text="Basic search configuration",
    )
    local = GraphLocalSearchConfigInputSerializer(
        required=False,
        help_text="Local search configuration",
    )
    global_ = GraphGlobalSearchConfigInputSerializer(
        required=False,
        help_text="Global search configuration",
    )
    drift = GraphDriftSearchConfigInputSerializer(
        required=False,
        help_text="Drift search configuration",
    )

    def get_fields(self):
        fields = super().get_fields()
        fields["global"] = fields.pop("global_")
        return fields


class GraphRagDocumentListSerializer(serializers.Serializer):
    graph_rag_document_id = serializers.IntegerField()
    document_id = serializers.IntegerField()
    file_name = serializers.CharField(source="document.file_name")
    file_size = serializers.IntegerField(source="document.file_size")
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
