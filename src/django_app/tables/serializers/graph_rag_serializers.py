from rest_framework import serializers
from tables.models.knowledge_models import (
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    GraphRagInputFileType,
    GraphRagChunkStrategyType,
)
from tables.serializers.knowledge_serializers import BaseRagTypeSerializer
from tables.constants.knowledge_constants import (
    GRAPHRAG_MIN_CHUNK_SIZE,
    GRAPHRAG_MAX_CHUNK_SIZE,
    GRAPHRAG_MIN_CHUNK_OVERLAP,
    GRAPHRAG_MAX_CHUNK_OVERLAP,
    GRAPHRAG_MIN_MAX_GLEANINGS,
    GRAPHRAG_MAX_MAX_GLEANINGS,
    GRAPHRAG_MIN_MAX_CLUSTER_SIZE,
    GRAPHRAG_MAX_MAX_CLUSTER_SIZE,
)


class GraphRagCreateSerializer(serializers.Serializer):
    """
    Serializer for creating GraphRag.
    """

    embedder_id = serializers.IntegerField(
        required=True, help_text="ID of the embedder to use"
    )
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
            "collection_id",
            "error_message",
            "created_at",
            "updated_at",
            "indexed_at",
        ]
        read_only_fields = fields


class GraphRagDocumentSerializer(serializers.ModelSerializer):
    """Serializer for GraphRagDocument."""

    document_id = serializers.IntegerField(
        source="document.document_id", read_only=True
    )
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
    documents = GraphRagDocumentSerializer(
        source="graph_rag_documents", many=True, read_only=True
    )
    total_documents_in_collection = serializers.SerializerMethodField()
    documents_in_graph_rag = serializers.SerializerMethodField()

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
            "collection_id",
            "collection_name",
            "index_config",
            "total_documents_in_collection",
            "documents_in_graph_rag",
            "documents",
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
            raise serializers.ValidationError(
                "At least one field must be provided for update"
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
        help_text="Custom basic search prompt",
    )
    k = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Number of text units to include (1-100)",
    )
    max_context_tokens = serializers.IntegerField(
        required=False,
        min_value=100,
        max_value=100000,
        help_text="Maximum context tokens (100-100000)",
    )


class GraphLocalSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for graph RAG local search config."""

    prompt = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Custom local search prompt",
    )
    text_unit_prop = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Text unit proportion (0.0-1.0)",
    )
    community_prop = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Community proportion (0.0-1.0)",
    )
    conversation_history_max_turns = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=50,
        help_text="Max conversation history turns (1-50)",
    )
    top_k_entities = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Top K entities (1-100)",
    )
    top_k_relationships = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Top K relationships (1-100)",
    )
    max_context_tokens = serializers.IntegerField(
        required=False,
        min_value=100,
        max_value=100000,
        help_text="Maximum context tokens (100-100000)",
    )


class GraphSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for graph RAG search config wrapper."""

    search_method = serializers.ChoiceField(
        choices=["basic", "local"],
        required=False,
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
