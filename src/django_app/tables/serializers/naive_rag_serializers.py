from rest_framework import serializers

from tables.constants.knowledge_constants import (
    MIN_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_OVERLAP,
    MAX_CHUNK_OVERLAP,
)
from tables.models.knowledge_models import (
    NaiveRag,
    NaiveRagDocumentConfig,
    NaiveRagChunk,
    NaiveRagPreviewChunk,
    NaiveRagSearchConfig,
)
from tables.serializers.knowledge_serializers import BaseRagTypeSerializer


class NaiveRagSerializer(serializers.ModelSerializer):
    """
    Serializer for NaiveRag details.
    Used for displaying NaiveRag information.
    """

    base_rag_type = BaseRagTypeSerializer(read_only=True)
    embedder_name = serializers.CharField(source="embedder.name", read_only=True)
    collection_id = serializers.IntegerField(
        source="base_rag_type.source_collection_id", read_only=True
    )

    class Meta:
        model = NaiveRag
        fields = [
            "naive_rag_id",
            "base_rag_type",
            "embedder",
            "embedder_name",
            "rag_status",
            "outdated_reasons",
            "collection_id",
            "error_message",
            "created_at",
            "updated_at",
            "indexed_at",
        ]
        read_only_fields = fields


class NaiveRagCreateUpdateSerializer(serializers.Serializer):
    """
    Serializer for creating/updating NaiveRag.
    """

    embedder_id = serializers.IntegerField(
        required=True, help_text="ID of the embedder to use"
    )

    def validate_embedder_id(self, value):
        """Validate embedder_id is positive."""
        if value <= 0:
            raise serializers.ValidationError("embedder_id must be positive")
        return value


class DocumentConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for displaying document configuration.
    """

    document_id = serializers.IntegerField(
        source="document.document_id", read_only=True
    )
    file_name = serializers.CharField(source="document.file_name", read_only=True)

    class Meta:
        model = NaiveRagDocumentConfig
        fields = [
            "naive_rag_document_id",
            "document_id",
            "file_name",
            "chunk_strategy",
            "chunk_size",
            "chunk_overlap",
            "additional_params",
            "status",
            "outdated_reasons",
            "error_message",
            "failed_at",
            "total_chunks",
            "total_embeddings",
            "created_at",
            "processed_at",
        ]
        read_only_fields = fields


class DocumentConfigWithErrorsSerializer(serializers.ModelSerializer):
    """
    Serializer for displaying document configuration with validation errors.
    Used in bulk update responses to show which configs failed and why.
    """

    document_id = serializers.IntegerField(
        source="document.document_id", read_only=True
    )
    file_name = serializers.CharField(source="document.file_name", read_only=True)
    errors = serializers.SerializerMethodField()

    class Meta:
        model = NaiveRagDocumentConfig
        fields = [
            "naive_rag_document_id",
            "document_id",
            "file_name",
            "chunk_strategy",
            "chunk_size",
            "chunk_overlap",
            "additional_params",
            "status",
            "outdated_reasons",
            "error_message",
            "failed_at",
            "total_chunks",
            "total_embeddings",
            "created_at",
            "processed_at",
            "errors",
        ]
        read_only_fields = [
            "naive_rag_document_id",
            "document_id",
            "file_name",
            "chunk_strategy",
            "chunk_size",
            "chunk_overlap",
            "additional_params",
            "status",
            "outdated_reasons",
            "error_message",
            "failed_at",
            "total_chunks",
            "total_embeddings",
            "created_at",
            "processed_at",
        ]

    def get_errors(self, obj):
        """
        Get validation errors for this config from context.
        Returns empty list if no errors.
        """
        config_errors = self.context.get("config_errors", {})
        return config_errors.get(obj.naive_rag_document_id, [])


class DocumentConfigUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating document config.
    All fields optional - only updates provided fields.
    """

    chunk_size = serializers.IntegerField(
        required=False,
        min_value=MIN_CHUNK_SIZE,
        max_value=MAX_CHUNK_SIZE,
        help_text="New chunk size",
    )
    chunk_overlap = serializers.IntegerField(
        required=False,
        min_value=MIN_CHUNK_OVERLAP,
        max_value=MAX_CHUNK_OVERLAP,
        help_text="New chunk overlap",
    )
    chunk_strategy = serializers.ChoiceField(
        required=False,
        choices=NaiveRagDocumentConfig.ChunkStrategy.choices,
        help_text="New chunking strategy",
    )
    additional_params = serializers.JSONField(
        required=False, help_text="New additional parameters"
    )

    def validate(self, attrs):
        """Ensure at least one field is provided."""
        if not attrs:
            raise serializers.ValidationError(
                "At least one field must be provided for update"
            )
        return attrs


class NaiveRagDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for NaiveRag with document configs.
    """

    base_rag_type = BaseRagTypeSerializer(read_only=True)
    embedder_name = serializers.CharField(source="embedder.name", read_only=True)
    collection_id = serializers.IntegerField(
        source="base_rag_type.source_collection_id", read_only=True
    )
    collection_name = serializers.CharField(
        source="base_rag_type.source_collection.collection_name", read_only=True
    )
    document_configs = DocumentConfigSerializer(
        source="naive_rag_configs", many=True, read_only=True
    )
    total_documents = serializers.SerializerMethodField()
    configured_documents = serializers.SerializerMethodField()

    class Meta:
        model = NaiveRag
        fields = [
            "naive_rag_id",
            "base_rag_type",
            "embedder",
            "embedder_name",
            "rag_status",
            "outdated_reasons",
            "collection_id",
            "collection_name",
            "total_documents",
            "configured_documents",
            "document_configs",
            "error_message",
            "created_at",
            "updated_at",
            "indexed_at",
        ]
        read_only_fields = fields

    def get_total_documents(self, obj):
        """Get total documents in collection."""
        return obj.base_rag_type.source_collection.documents.count()

    def get_configured_documents(self, obj):
        """Get count of configured documents."""
        return obj.naive_rag_configs.count()


class DocumentConfigBulkUpdateSerializer(serializers.Serializer):
    id = serializers.IntegerField(
        required=True,
        help_text="Primary Key of Document Config.",
    )

    chunk_size = serializers.IntegerField(
        required=False,
        min_value=MIN_CHUNK_SIZE,
        max_value=MAX_CHUNK_SIZE,
        help_text="New chunk size (applied to all selected configs)",
    )
    chunk_overlap = serializers.IntegerField(
        required=False,
        min_value=MIN_CHUNK_OVERLAP,
        max_value=MAX_CHUNK_OVERLAP,
        help_text="New chunk overlap (applied to all selected configs)",
    )
    chunk_strategy = serializers.ChoiceField(
        required=False,
        choices=NaiveRagDocumentConfig.ChunkStrategy.choices,
        help_text="New chunking strategy (applied to all selected configs)",
    )
    additional_params = serializers.JSONField(
        required=False,
        help_text="New additional parameters (applied to all selected configs)",
    )

    default_error_messages = {
        "empty_data_to_update": "At least one field must be provided to update config id={id}",
    }

    def validate(self, attrs):
        if not any(f in attrs for f in self.fields if f != "id"):
            self.fail("empty_data_to_update", id=attrs["id"])
        return attrs


class DocumentConfigBulkDeleteSerializer(serializers.Serializer):
    """
    Serializer for bulk deleting document configs.
    Deletes multiple configs by their config IDs.
    """

    config_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_empty=False,
        help_text="List of naive_rag_document_config IDs to delete",
    )

    def validate_config_ids(self, value):
        """Validate config_ids list is not empty."""
        if not value:
            raise serializers.ValidationError("config_ids list cannot be empty")
        # Remove duplicates
        return list(set(value))


class NaiveRagChunkSerializer(serializers.ModelSerializer):
    """Serializer for indexed chunks."""

    class Meta:
        model = NaiveRagChunk
        fields = [
            "chunk_id",
            "text",
            "chunk_index",
            "token_count",
            "overlap_start_index",
            "overlap_end_index",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class NaiveRagPreviewChunkSerializer(serializers.ModelSerializer):
    """Serializer for preview chunks."""

    class Meta:
        model = NaiveRagPreviewChunk
        fields = [
            "preview_chunk_id",
            "text",
            "chunk_index",
            "token_count",
            "overlap_start_index",
            "overlap_end_index",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class ChunkingResponseSerializer(serializers.Serializer):
    """
    Response serializer for process-chunking endpoint.
    """

    chunking_job_id = serializers.CharField()
    naive_rag_id = serializers.IntegerField()
    document_config_id = serializers.IntegerField()
    status = serializers.CharField()  # "completed", "failed", "cancelled", "timeout"
    chunk_count = serializers.IntegerField(allow_null=True)
    message = serializers.CharField(allow_null=True, allow_blank=True)
    elapsed_time = serializers.FloatField(
        allow_null=True, help_text="Chunking duration in seconds"
    )


class ChunkPreviewResponseSerializer(serializers.Serializer):
    """
    Response serializer for GET chunks endpoint.
    Supports pagination for endless scrolling.
    """

    naive_rag_id = serializers.IntegerField()
    document_config_id = serializers.IntegerField()
    status = serializers.CharField()
    total_chunks = serializers.IntegerField()
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    chunks = serializers.ListField(child=serializers.DictField())


class NaiveRagLightSerializer(serializers.ModelSerializer):
    """Lightweight serializer for dropdown lists."""

    collection_id = serializers.IntegerField(
        source="base_rag_type.source_collection_id", read_only=True
    )

    class Meta:
        model = NaiveRag
        fields = [
            "naive_rag_id",
            "rag_status",
            "collection_id",
            "created_at",
            "indexed_at",
        ]
        read_only_fields = fields


class AssignRagSerializer(serializers.Serializer):
    """Input serializer for assign-rag action."""

    naive_rag_id = serializers.IntegerField(required=True)


class NaiveRagSearchConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = NaiveRagSearchConfig
        fields = ["search_limit", "similarity_threshold", "is_suggested"]


class NaiveSearchConfigInputSerializer(serializers.Serializer):
    """Input serializer for naive RAG search config."""

    search_limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        help_text="Number of chunks to retrieve (1-1000)",
    )
    similarity_threshold = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Similarity threshold for search (0.0-1.0)",
    )
    is_suggested = serializers.BooleanField(
        required=False,
        help_text="Whether these values came from parameter suggestion.",
    )


class ChunkSearchRequestSerializer(serializers.Serializer):
    """Query params for NaiveRagChunkSearchView."""

    q = serializers.CharField(
        required=True,
        trim_whitespace=False,
        help_text="Search query (case-insensitive substring match, spaces preserved)",
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Max number of chunk IDs to return",
    )
    offset = serializers.IntegerField(
        required=False,
        min_value=0,
        default=0,
        help_text="Number of chunk IDs to skip",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        default_limit = self.context.get("default_limit")
        if default_limit is not None:
            self.fields["limit"].default = default_limit

    def validate_limit(self, value):
        max_limit = self.context.get("max_limit")
        if max_limit is not None:
            return min(value, max_limit)
        return value


class ChunkSearchResponseSerializer(serializers.Serializer):
    """Response serializer for chunk search endpoint."""

    naive_rag_id = serializers.IntegerField()
    document_config_id = serializers.IntegerField()
    query = serializers.CharField()
    total_matches = serializers.IntegerField()
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    preview_chunk_ids = serializers.ListField(child=serializers.IntegerField())


class PreviewChunksByIdsRequestSerializer(serializers.Serializer):
    """Request serializer for fetching preview chunks by a list of ids."""

    preview_chunk_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=True,
        allow_empty=False,
        help_text="List of preview_chunk_id values to fetch",
    )


class PreviewChunksByIdsResponseSerializer(serializers.Serializer):
    """Response serializer for fetching preview chunks by a list of ids."""

    naive_rag_id = serializers.IntegerField()
    document_config_id = serializers.IntegerField()
    total = serializers.IntegerField()
    chunks = NaiveRagPreviewChunkSerializer(many=True)


class ChunkingConfigSerializer(serializers.Serializer):
    chunk_strategy = serializers.ChoiceField(
        choices=NaiveRagDocumentConfig.ChunkStrategy.choices
    )
    chunk_size = serializers.IntegerField(
        min_value=MIN_CHUNK_SIZE,
        max_value=MAX_CHUNK_SIZE,
    )
    chunk_overlap = serializers.IntegerField(
        min_value=MIN_CHUNK_OVERLAP,
        max_value=MAX_CHUNK_OVERLAP,
    )
    additional_params = serializers.JSONField(default=dict)

    def validate(self, attrs):
        chunk_size = attrs["chunk_size"]
        chunk_overlap = attrs["chunk_overlap"]
        if chunk_overlap >= chunk_size:
            raise serializers.ValidationError(
                {"chunk_overlap": ["'chunk_overlap' must be less then 'chunk_size'"]}
            )
        return attrs
