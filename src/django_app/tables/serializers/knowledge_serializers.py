import itertools

from rest_framework import serializers
from loguru import logger
from django.db.models import Count, F

from tables.models.knowledge_models import (
    SourceCollection,
    DocumentMetadata,
    BaseRagType,
    NaiveRag,
    GraphRag,
)
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)


COLLECTION_DESCRIPTION_MAX_LENGTH = 2000


def validate_collection_description(value):
    """Shared length validation for SourceCollection.description.

    The value is injected verbatim into every knowledge tool description sent
    to the LLM, so an unbounded length would bloat every prompt.
    """
    if value and len(value) > COLLECTION_DESCRIPTION_MAX_LENGTH:
        raise serializers.ValidationError(
            f"Description must be {COLLECTION_DESCRIPTION_MAX_LENGTH} characters or less."
        )
    return value


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
    indexing_document_config_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="IDs of document configs included in the current/last indexing run",
    )
    processing_document_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="IDs of documents in the current/last graph rag indexing run",
    )
    message = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Additional message (e.g., error or status info)",
    )
    outdated_reasons = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Outdated reasons for this RAG configuration.",
    )
    created_at = serializers.DateTimeField(
        help_text="When this RAG configuration was created"
    )
    updated_at = serializers.DateTimeField(
        help_text="When this RAG configuration was last updated"
    )


class RagConfigurationBriefSerializer(serializers.Serializer):
    """
    Compact RAG configuration summary nested inside a SourceCollection.
    """

    rag_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the specific RAG implementation (e.g., NaiveRag.naive_rag_id)",
    )
    rag_type = serializers.ChoiceField(
        choices=["naive", "graph"], help_text="Type of RAG implementation"
    )
    status = serializers.CharField(help_text="Current processing status of the RAG")


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


class CopyDocumentsSerializer(serializers.Serializer):
    """
    Serializer for copying documents into a target collection.
    """

    collection_id = serializers.IntegerField(
        min_value=1, help_text="ID of the target collection to copy documents into"
    )
    document_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="List of document IDs to copy",
    )

    def validate_document_ids(self, value):
        return list(dict.fromkeys(value))


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
    Shows basic collection info plus a compact view of available RAG
    configurations (``rag_id``/``rag_type``/``status``). The full RAG summary is
    served by the retrieve endpoint.
    """

    document_count = serializers.IntegerField(
        read_only=True,
    )
    rag_configurations = serializers.SerializerMethodField(
        help_text="Compact list of RAG configurations (rag_id, rag_type, status)"
    )

    class Meta:
        model = SourceCollection
        fields = [
            "collection_id",
            "collection_name",
            "description",
            "user_id",
            "status",
            "document_count",
            "rag_configurations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_rag_configurations(self, obj):
        """Compact RAG configs (rag_id/rag_type/status) for the collection list.

        Queries NaiveRag/GraphRag directly (one query each) and merges them; the
        rag_type comes from the BaseRagType discriminator column. Returns ``[]``
        on error so one bad collection never breaks the list.
        """
        try:
            naive_rags = (
                NaiveRag.objects.filter(base_rag_type__source_collection=obj)
                .annotate(
                    rag_id=F("naive_rag_id"),
                    rag_type=F("base_rag_type__rag_type"),
                    status=F("rag_status"),
                )
                .values("rag_id", "rag_type", "status")
            )
            graph_rags = (
                GraphRag.objects.filter(base_rag_type__source_collection=obj)
                .annotate(
                    rag_id=F("graph_rag_id"),
                    rag_type=F("base_rag_type__rag_type"),
                    status=F("rag_status"),
                )
                .values("rag_id", "rag_type", "status")
            )
            rag_configs = list(itertools.chain(naive_rags, graph_rags))
            return RagConfigurationBriefSerializer(rag_configs, many=True).data
        except Exception as e:
            logger.error(
                f"Error fetching RAG configurations for collection {obj.collection_id}: {e}"
            )
            return []


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
            "description",
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
            naive_rags = (
                NaiveRag.objects.filter(base_rag_type__source_collection=obj)
                .select_related("embedder")
                .annotate(
                    document_configs_count=Count("naive_rag_configs", distinct=True),
                    chunks_count=Count("naive_rag_configs__chunks", distinct=True),
                    embeddings_count=Count(
                        "naive_rag_configs__embeddings", distinct=True
                    ),
                )
            )
            graph_rags = (
                GraphRag.objects.filter(base_rag_type__source_collection=obj)
                .select_related("embedder", "llm")
                .annotate(documents_count=Count("graph_rag_documents"))
            )
            rag_configs = [
                *(
                    CollectionManagementService._get_naive_rag_summary(r)
                    for r in naive_rags
                ),
                *(
                    CollectionManagementService._get_graph_rag_summary(r)
                    for r in graph_rags
                ),
            ]
            return RagConfigurationSummarySerializer(rag_configs, many=True).data
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
            "description",
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
            "description": {"required": False, "allow_blank": True},
            "user_id": {"required": False},
        }
        validators = []

    def validate_collection_name(self, value):
        if value and len(value) > 255:
            raise serializers.ValidationError(
                "Collection name must be 255 characters or less."
            )
        return value

    def validate_description(self, value):
        return validate_collection_description(value)


class SourceCollectionUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating collection.
    Only allows updating collection_name.
    """

    class Meta:
        model = SourceCollection
        fields = ["collection_name", "description"]
        extra_kwargs = {
            "description": {"required": False, "allow_blank": True},
        }

    def validate_collection_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Collection name cannot be empty.")
        if len(value) > 255:
            raise serializers.ValidationError(
                "Collection name must be 255 characters or less."
            )
        return value

    def validate_description(self, value):
        return validate_collection_description(value)


class UpdateSourceCollectionSerializer(serializers.ModelSerializer):
    """
    Serializer for updating only specific fields of a SourceCollection.
    """

    class Meta:
        model = SourceCollection
        fields = ["collection_name", "description"]
        validators = []

    def validate_description(self, value):
        return validate_collection_description(value)


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
