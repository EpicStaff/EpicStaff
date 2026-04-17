from rest_framework import serializers
from loguru import logger

from tables.models.knowledge_models import (
    SourceCollection,
    DocumentMetadata,
    BaseRagType,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)


class RagConfigurationSummarySerializer(serializers.Serializer):
    """
    Serializer for RAG configuration summary.
    Used for displaying RAG implementations available for a collection.

    This is a non-model serializer since it aggregates data from multiple models.
    """

    rag_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the specific RAG implementation (e.g., NaiveRag.naive_rag_id)",
    )
    rag_type = serializers.ChoiceField(
        choices=["naive", "graph"], help_text="Type of RAG implementation"
    )
    status = serializers.CharField(help_text="Current processing status of the RAG")
    is_ready_for_indexing = serializers.BooleanField(
        help_text="Whether this RAG configuration is ready to be indexed"
    )
    embedder_name = serializers.CharField(
        allow_null=True, required=False, help_text="Name of the embedder model"
    )
    embedder_id = serializers.IntegerField(
        allow_null=True, required=False, help_text="ID of the embedder configuration"
    )
    document_configs_count = serializers.IntegerField(
        required=False, help_text="Number of document configurations"
    )
    chunks_count = serializers.IntegerField(
        required=False, help_text="Total number of chunks generated"
    )
    embeddings_count = serializers.IntegerField(
        required=False, help_text="Total number of embeddings created"
    )
    message = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Additional message (e.g., error or status info)",
    )
    created_at = serializers.DateTimeField(
        help_text="When this RAG configuration was created"
    )
    updated_at = serializers.DateTimeField(
        help_text="When this RAG configuration was last updated"
    )


class BaseRagTypeSerializer(serializers.ModelSerializer):
    """Serializer for BaseRagType."""

    class Meta:
        model = BaseRagType
        fields = [
            "rag_type_id",
            "rag_type",
            "source_collection",
        ]
        read_only_fields = fields


class DocumentMetadataSerializer(serializers.ModelSerializer):
    """
    Serializer for DocumentMetadata.
    Used for displaying uploaded document information.
    """

    class Meta:
        model = DocumentMetadata
        fields = [
            "document_id",
            "file_name",
            "file_type",
            "file_size",
            "source_collection",
        ]
        read_only_fields = fields


class DocumentListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing documents in a collection.
    """

    class Meta:
        model = DocumentMetadata
        fields = [
            "document_id",
            "file_name",
            "file_type",
            "file_size",
        ]
        read_only_fields = fields


class DocumentUploadSerializer(serializers.Serializer):
    """
    Serializer for uploading documents to a collection.
    Handles multiple file uploads (drag & drop support).
    """

    files = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        write_only=True,
        help_text="List of files to upload (supports multiple files)",
    )

    def validate_files(self, value):
        """
        Basic validation - just ensure files list is not empty.
        Detailed validation is done in DocumentManagementService.
        """
        if not value:
            raise serializers.ValidationError("At least one file must be provided.")
        return value


class DocumentBulkDeleteSerializer(serializers.Serializer):
    """
    Serializer for bulk deletion of documents.
    Accepts list of document IDs to delete.
    """

    document_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text="List of document IDs to delete",
    )

    def validate_document_ids(self, value):
        """
        Validate document IDs list.
        """
        if not value:
            raise serializers.ValidationError(
                "At least one document ID must be provided."
            )

        # Remove duplicates
        unique_ids = list(set(value))

        return unique_ids


class DocumentDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for single document view.
    """

    collection_name = serializers.CharField(
        source="source_collection.collection_name", read_only=True
    )

    class Meta:
        model = DocumentMetadata
        fields = [
            "document_id",
            "file_name",
            "file_type",
            "file_size",
            "source_collection",
            "collection_name",
        ]
        read_only_fields = fields


class SourceCollectionListSerializer(serializers.ModelSerializer):
    """
    Serializer for listing collections.
    Shows basic collection info without related documents.
    """

    document_count = serializers.IntegerField(source="documents.count", read_only=True)

    class Meta:
        model = SourceCollection
        fields = [
            "collection_id",
            "collection_name",
            "user_id",
            "status",
            "document_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SourceCollectionDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for retrieving a single collection with all details.
    Includes RAG configurations to show what RAG types are available.
    """

    document_count = serializers.IntegerField(source="documents.count", read_only=True)
    rag_configurations = serializers.SerializerMethodField(
        help_text="List of RAG configurations for this collection (NaiveRag, GraphRag, etc.)"
    )

    class Meta:
        model = SourceCollection
        fields = [
            "collection_id",
            "collection_name",
            "user_id",
            "status",
            "document_count",
            "rag_configurations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_rag_configurations(self, obj):
        """
        Get all RAG configurations for this collection.
        Business logic is delegated to CollectionManagementService.
        """

        try:
            rag_configs = CollectionManagementService.get_rag_configurations(
                obj.collection_id
            )
            serializer = RagConfigurationSummarySerializer(rag_configs, many=True)
            return serializer.data
        except Exception as e:
            logger.error(
                f"Error fetching RAG configurations for collection {obj.collection_id}: {e}"
            )
            return []


class SourceCollectionCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a new empty collection.
    """

    class Meta:
        model = SourceCollection
        fields = [
            "collection_id",
            "collection_name",
            "user_id",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "collection_id",
            "status",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "collection_name": {"required": False, "allow_blank": True},
            "user_id": {"required": False},
        }
        validators = []

    def validate_collection_name(self, value):
        if value and len(value) > 255:
            raise serializers.ValidationError(
                "Collection name must be 255 characters or less."
            )
        return value


class SourceCollectionUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating collection.
    Only allows updating collection_name.
    """

    class Meta:
        model = SourceCollection
        fields = ["collection_name"]

    def validate_collection_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Collection name cannot be empty.")
        if len(value) > 255:
            raise serializers.ValidationError(
                "Collection name must be 255 characters or less."
            )
        return value


class UpdateSourceCollectionSerializer(serializers.ModelSerializer):
    """
    Serializer for updating only specific fields of a SourceCollection.
    """

    class Meta:
        model = SourceCollection
        fields = ["collection_name"]
        validators = []


class CopySourceCollectionSerializer(serializers.Serializer):
    new_collection_name = serializers.CharField(required=False)


class RagInputSerializer(serializers.Serializer):
    """
    Input serializer for rag field in Agent create/update.
    """

    rag_type = serializers.ChoiceField(
        choices=["naive", "graph"], help_text="Type of RAG implementation"
    )
    rag_id = serializers.IntegerField(min_value=1, help_text="ID of the RAG instance")


class NestedSearchConfigSerializer(serializers.Serializer):
    """
    Nested search config serializer
    Handles multiple RAG types: {"naive": {...}, "graph": {...}}

    Uses get_fields() for lazy imports to avoid circular dependencies
    """

    def get_fields(self):
        from tables.serializers.naive_rag_serializers import (
            NaiveSearchConfigInputSerializer,
        )
        from tables.serializers.graph_rag_serializers import (
            GraphSearchConfigInputSerializer,
        )

        fields = super().get_fields()
        fields["naive"] = NaiveSearchConfigInputSerializer(
            required=False, help_text="Naive RAG search config"
        )
        fields["graph"] = GraphSearchConfigInputSerializer(
            required=False, help_text="Graph RAG search config"
        )
        return fields

    def validate(self, attrs):
        """Ensure at least one RAG type is provided."""
        if not attrs:
            raise serializers.ValidationError(
                "At least one RAG type must be provided (e.g., 'naive', 'graph')"
            )
        return attrs
