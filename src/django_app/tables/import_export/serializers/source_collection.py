"""Export shape of a knowledge collection and where its files sit inside the archive."""

from rest_framework import serializers

from tables.models.knowledge_models import (
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    NaiveRag,
    NaiveRagDocumentConfig,
    SourceCollection,
)


def document_member(document_id: int) -> str:
    return f"knowledge/documents/{document_id}"


def naive_chunks_member(naive_rag_id: int, document_config_id: int) -> str:
    return f"knowledge/naive/{naive_rag_id}/{document_config_id}.jsonl"


def graph_artifacts_member(graph_rag_id: int) -> str:
    return f"knowledge/graph/{graph_rag_id}.tar"


class DocumentExportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="document_id")
    content_path = serializers.SerializerMethodField()

    class Meta:
        model = DocumentMetadata
        fields = ["id", "file_name", "file_type", "file_size", "content_path"]

    def get_content_path(self, document: DocumentMetadata) -> str | None:
        # A document without stored content has no file in the archive.
        if document.document_content_id is None:
            return None
        return document_member(document.document_id)


class NaiveRagDocumentConfigExportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="naive_rag_document_id")
    chunks_path = serializers.SerializerMethodField()

    class Meta:
        model = NaiveRagDocumentConfig
        fields = [
            "id",
            "document",
            "chunk_strategy",
            "chunk_size",
            "chunk_overlap",
            "additional_params",
            "status",
            "indexed_chunk_strategy",
            "indexed_chunk_size",
            "indexed_chunk_overlap",
            "indexed_additional_params",
            "chunks_path",
        ]

    def get_chunks_path(self, config: NaiveRagDocumentConfig) -> str | None:
        if config.status == NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED:
            return naive_chunks_member(config.naive_rag_id, config.naive_rag_document_id)
        return None


class NaiveRagExportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="naive_rag_id")
    document_configs = serializers.SerializerMethodField()

    class Meta:
        model = NaiveRag
        fields = ["id", "embedder", "rag_status", "document_configs"]

    def get_document_configs(self, naive_rag: NaiveRag) -> list[dict]:
        return NaiveRagDocumentConfigExportSerializer(
            naive_rag.naive_rag_configs.order_by("naive_rag_document_id"), many=True
        ).data


class GraphRagIndexConfigExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphRagIndexConfig
        fields = [
            "file_type",
            "chunk_size",
            "chunk_overlap",
            "chunk_strategy",
            "entity_types",
            "max_gleanings",
            "max_cluster_size",
        ]


class GraphRagDocumentExportSerializer(serializers.ModelSerializer):
    # The GraphRAG index stores this id, not the document's; import maps it old -> new.
    id = serializers.IntegerField(source="graph_rag_document_id")

    class Meta:
        model = GraphRagDocument
        fields = ["id", "document", "status"]


class GraphRagExportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="graph_rag_id")
    index_config = GraphRagIndexConfigExportSerializer(allow_null=True)
    documents = GraphRagDocumentExportSerializer(source="graph_rag_documents", many=True)
    artifacts_path = serializers.SerializerMethodField()

    class Meta:
        model = GraphRag
        fields = [
            "id",
            "embedder",
            "llm",
            "rag_status",
            "index_config",
            "documents",
            "artifacts_path",
        ]

    def get_artifacts_path(self, graph_rag: GraphRag) -> str | None:
        if graph_rag.rag_status == GraphRag.GraphRagStatus.COMPLETED:
            return graph_artifacts_member(graph_rag.graph_rag_id)
        return None


class SourceCollectionExportSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="collection_id")
    documents = DocumentExportSerializer(many=True)
    naive_rags = serializers.SerializerMethodField()
    graph_rags = serializers.SerializerMethodField()

    class Meta:
        model = SourceCollection
        fields = [
            "id",
            "collection_name",
            "description",
            "collection_origin",
            "documents",
            "naive_rags",
            "graph_rags",
        ]

    def get_naive_rags(self, collection: SourceCollection) -> list[dict]:
        return NaiveRagExportSerializer(
            NaiveRag.objects.filter(base_rag_type__source_collection=collection), many=True
        ).data

    def get_graph_rags(self, collection: SourceCollection) -> list[dict]:
        return GraphRagExportSerializer(
            GraphRag.objects.filter(base_rag_type__source_collection=collection).select_related(
                "index_config"
            ),
            many=True,
        ).data
