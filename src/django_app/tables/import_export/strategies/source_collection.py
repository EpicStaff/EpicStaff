import json
import tempfile

from django.db.models import Q
from rest_framework.exceptions import ValidationError

from tables.clients.knowledge import KnowledgeClient
from tables.import_export.archive import ExportArchiveWriter
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.source_collection import (
    SourceCollectionExportSerializer,
    document_member,
    graph_artifacts_member,
    naive_chunks_member,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.models.knowledge_models import (
    DocumentContent,
    GraphRag,
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    SourceCollection,
)

# Rows read per database round trip while writing chunks; a collection can hold
# hundreds of thousands, so they are never loaded at once.
_CHUNK_BATCH_SIZE = 1000
_CHUNK_FIELDS = (
    "chunk_index",
    "text",
    "token_count",
    "overlap_start_index",
    "overlap_end_index",
    "metadata",
    "embedding__vector",
)


class SourceCollectionStrategy(EntityImportExportStrategy):
    """Export a knowledge collection with its documents and completed index data."""

    entity_type = EntityType.SOURCE_COLLECTION
    serializer_class = SourceCollectionExportSerializer

    def get_instance(self, entity_id: int) -> SourceCollection | None:
        return SourceCollection.objects.filter(collection_id=entity_id).first()

    def get_preview_data(self, instance: SourceCollection) -> dict:
        return {"id": instance.collection_id, "name": instance.collection_name}

    def get_org_scope_q(self, org_id: int | None) -> Q:
        if org_id is None:
            return Q()
        return Q(org_id=org_id)

    def extract_dependencies_from_instance(
        self, instance: SourceCollection
    ) -> dict[str, list[int]]:
        embeders = [
            *NaiveRag.objects.filter(
                base_rag_type__source_collection=instance, embedder__isnull=False
            ).values_list("embedder_id", flat=True),
            *GraphRag.objects.filter(
                base_rag_type__source_collection=instance, embedder__isnull=False
            ).values_list("embedder_id", flat=True),
        ]
        llm_ids = GraphRag.objects.filter(
            base_rag_type__source_collection=instance, llm__isnull=False
        ).values_list("llm_id", flat=True)

        embeders = sorted(set(embeders))
        llm_ids = sorted(set(llm_ids))

        return {EntityType.EMBEDDING_CONFIG: embeders, EntityType.LLM_CONFIG: llm_ids}

    def export_entity(self, instance: SourceCollection) -> dict:
        return SourceCollectionExportSerializer(instance).data

    def write_archive_members(
        self, instance: SourceCollection, writer: ExportArchiveWriter
    ) -> None:
        """Write the collection's documents and completed index data into the archive.

        Members are named exactly as `export_entity` points to them. Nothing larger
        than one document is held in memory.
        """
        self._write_documents(instance, writer)
        self._write_naive_chunks(instance, writer)
        self._write_graph_artifacts(instance, writer)

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs):
        raise ValidationError(
            {"code": "unsupported", "detail": "Knowledge collections cannot be imported yet."}
        )

    def _write_documents(self, instance: SourceCollection, writer: ExportArchiveWriter) -> None:
        for document in instance.documents.all():
            content = (
                DocumentContent.objects.filter(metadata_records=document)
                .values_list("content", flat=True)
                .first()
            )
            if content is None:
                continue
            writer.add_bytes(document_member(document.document_id), bytes(content))

    def _write_naive_chunks(self, instance: SourceCollection, writer: ExportArchiveWriter) -> None:
        configs = NaiveRagDocumentConfig.objects.filter(
            naive_rag__base_rag_type__source_collection=instance,
            status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED,
        )
        for config in configs:
            with tempfile.TemporaryFile() as lines:
                rows = (
                    NaiveRagChunk.objects.filter(naive_rag_document_config=config)
                    .order_by("chunk_index")
                    .values_list(*_CHUNK_FIELDS)
                    .iterator(chunk_size=_CHUNK_BATCH_SIZE)
                )
                for row in rows:
                    chunk = dict(zip(_CHUNK_FIELDS, row, strict=True))
                    vector = chunk.pop("embedding__vector")
                    chunk["vector"] = vector.tolist() if vector is not None else None
                    lines.write(json.dumps(chunk).encode() + b"\n")
                lines.seek(0)
                writer.add_file(
                    naive_chunks_member(config.naive_rag_id, config.naive_rag_document_id),
                    lines,
                )

    def _write_graph_artifacts(
        self, instance: SourceCollection, writer: ExportArchiveWriter
    ) -> None:
        rags = GraphRag.objects.filter(
            base_rag_type__source_collection=instance, rag_status=GraphRag.GraphRagStatus.COMPLETED
        )
        if not rags:
            return
        with KnowledgeClient() as client:
            for rag in rags:
                with tempfile.TemporaryFile() as tar:
                    client.download_graph_artifacts(rag.graph_rag_id, tar)
                    tar.seek(0)
                    writer.add_file(graph_artifacts_member(rag.graph_rag_id), tar)
