"""Export and import of a knowledge collection with its documents and index data."""

import json
import re
import tempfile
from collections import Counter

from django.db.models import Case, IntegerField, Q, Value, When
from loguru import logger
from rbac.authorship.policy import resolve_author
from rest_framework.exceptions import ValidationError
from src.shared.enums.knowledge_new import RAGStrategy

from tables.clients.knowledge import KnowledgeClient
from tables.import_export.archive import ExportArchiveWriter, ImportArchive
from tables.import_export.constants import MAX_REUSE_CANDIDATES
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
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    GraphRag,
    GraphRagDocument,
    GraphRagIndexConfig,
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
    NaiveRagEmbedding,
    SourceCollection,
)

# Rows read or written per database round trip for chunks; a collection can hold
# hundreds of thousands, so they are never all in memory at once.
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
# What one line of a chunks file sets on a chunk; anything else in the line is ignored.
_IMPORTED_CHUNK_FIELDS = (
    "chunk_index",
    "text",
    "token_count",
    "overlap_start_index",
    "overlap_end_index",
    "metadata",
)
_CONFIG_SETTING_FIELDS = ("chunk_strategy", "chunk_size", "chunk_overlap", "additional_params")
_CONFIG_INDEXED_FIELDS = (
    "indexed_chunk_strategy",
    "indexed_chunk_size",
    "indexed_chunk_overlap",
    "indexed_additional_params",
)
_LINE_READ_SIZE = 1024 * 1024
# IDMapper keys for the RAGs inside a collection; knowledge links remap rag ids through them.
NAIVE_RAG_KEY = "NaiveRag"
GRAPH_RAG_KEY = "GraphRag"

# (count of each (file name, file size), set of RAG types)
_ReuseKey = tuple[Counter, frozenset]


def remove_restored_graph_indexes(graph_rag_ids: list[int]) -> None:
    """Delete graph indexes an import restored before it rolled back.

    Best effort: the import has already failed and must report that failure,
    not a failed cleanup.
    """
    if not graph_rag_ids:
        return
    with KnowledgeClient(timeout=5) as client:
        for rag_id in graph_rag_ids:
            try:
                client.delete(RAGStrategy.GRAPH, rag_id)
            except Exception:
                logger.exception("Could not remove restored graph index {}", rag_id)


def _iter_lines(member):
    """Yield the lines of a member without holding it whole in memory."""
    pending = b""
    while chunk := member.read(_LINE_READ_SIZE):
        pending += chunk
        *lines, pending = pending.split(b"\n")
        yield from lines
    if pending:
        yield pending


def _refuse(reason: str) -> ValidationError:
    return ValidationError({"code": "invalid_archive", "detail": reason})


class SourceCollectionStrategy(EntityImportExportStrategy):
    """Export and import a knowledge collection with its documents and completed index data.

    Only completed index data travels. On import a RAG that arrives without index
    data starts over as new, and its status is worked out from its documents.
    """

    entity_type = EntityType.SOURCE_COLLECTION
    serializer_class = SourceCollectionExportSerializer
    reuse_when_main = True

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

    # --- reuse ---------------------------------------------------------------------

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int | None = None
    ) -> SourceCollection | None:
        """Reuse a collection with the same name (or a renamed copy of it), description,
        files and RAG types."""
        name = data["collection_name"]
        # A name clash on save is renamed to "Name (1)", "Name (2)" and so on.
        candidates = (
            SourceCollection.objects.filter(self.get_org_scope_q(org_id))
            .filter(
                Q(collection_name=name) | Q(collection_name__regex=rf"^{re.escape(name)} \(\d+\)$")
            )
            .annotate(
                is_renamed_copy=Case(
                    When(collection_name=name, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by("is_renamed_copy", "-collection_id")[:MAX_REUSE_CANDIDATES]
        )
        wanted = self._reuse_key_of_entry(data)
        for candidate in candidates:
            if (
                candidate.description == data["description"]
                and self._reuse_key_of_collection(candidate) == wanted
            ):
                self._map_rags_on_reuse(data, candidate, id_mapper)
                return candidate
        return None

    @staticmethod
    def _reuse_key_of_entry(data: dict) -> _ReuseKey:
        # A Counter compares the file count and the set of files in one go.
        files = Counter(
            (document["file_name"], document["file_size"]) for document in data["documents"]
        )
        rag_types = set()
        if data["naive_rags"]:
            rag_types.add(BaseRagType.RagType.NAIVE)
        if data["graph_rags"]:
            rag_types.add(BaseRagType.RagType.GRAPH)
        return files, frozenset(rag_types)

    @staticmethod
    def _reuse_key_of_collection(collection: SourceCollection) -> _ReuseKey:
        files = Counter(collection.documents.values_list("file_name", "file_size"))
        rag_types = frozenset(collection.rag_types.values_list("rag_type", flat=True))
        return files, rag_types

    @staticmethod
    def _map_rags_on_reuse(data: dict, collection: SourceCollection, id_mapper: IDMapper) -> None:
        naive_rag = (
            NaiveRag.objects.filter(base_rag_type__source_collection=collection)
            .order_by("naive_rag_id")
            .first()
        )
        graph_rag = (
            GraphRag.objects.filter(base_rag_type__source_collection=collection)
            .order_by("graph_rag_id")
            .first()
        )
        if naive_rag is not None:
            for entry in data["naive_rags"]:
                id_mapper.map(NAIVE_RAG_KEY, entry["id"], naive_rag.naive_rag_id, was_created=False)
        if graph_rag is not None:
            for entry in data["graph_rags"]:
                id_mapper.map(GRAPH_RAG_KEY, entry["id"], graph_rag.graph_rag_id, was_created=False)

    # --- create --------------------------------------------------------------------

    def create_entity(
        self,
        data: dict,
        id_mapper: IDMapper,
        *,
        archive: ImportArchive | None = None,
        created_graph_rag_ids: list[int] | None = None,
        org_id: int | None = None,
        user=None,
        **kwargs,
    ) -> SourceCollection:
        """Create the collection, its documents, chunks and graph indexes.

        A graph index is restored in the knowledge service, outside the database
        transaction; its RAG id goes to `created_graph_rag_ids` before the upload so
        a failed import can remove it again.
        """
        if archive is None:
            raise ValidationError(
                {
                    "code": "archive_required",
                    "detail": "A knowledge collection can only be imported from an archive.",
                }
            )
        if created_graph_rag_ids is None:
            created_graph_rag_ids = []

        collection = SourceCollection.objects.create(
            collection_name=data["collection_name"],
            description=data["description"],
            collection_origin=data["collection_origin"],
            org_id=org_id,
            created_by=resolve_author(user),
        )
        document_ids = self._create_documents(data["documents"], collection, archive)
        collection.update_collection_status()

        for entry in data["naive_rags"]:
            self._create_naive_rag(entry, collection, document_ids, archive, id_mapper)
        for entry in data["graph_rags"]:
            self._create_graph_rag(
                entry, collection, document_ids, archive, id_mapper, created_graph_rag_ids
            )
        return collection

    @staticmethod
    def _create_documents(
        documents: list[dict], collection: SourceCollection, archive: ImportArchive
    ) -> dict[int, int]:
        """Create every document, one at a time; returns old document id -> new."""
        document_ids = {}
        for entry in documents:
            content = None
            file_size = entry["file_size"]
            if entry["content_path"] is not None:
                with archive.open_member(entry["content_path"]) as member:
                    data = member.read()
                content = DocumentContent.objects.create(content=data)
                # The bytes are the truth; the declared size could be anything.
                file_size = len(data)
            document = DocumentMetadata.objects.create(
                source_collection=collection,
                document_content=content,
                file_name=entry["file_name"],
                file_type=entry["file_type"],
                file_size=file_size,
            )
            document_ids[entry["id"]] = document.document_id
        return document_ids

    def _create_naive_rag(
        self,
        entry: dict,
        collection: SourceCollection,
        document_ids: dict[int, int],
        archive: ImportArchive,
        id_mapper: IDMapper,
    ) -> None:
        base = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
        )
        naive_rag = NaiveRag.objects.create(
            base_rag_type=base,
            embedder_id=id_mapper.get_or_none(EntityType.EMBEDDING_CONFIG, entry["embedder"]),
        )
        # Creating the RAG already added a config per document; fill those in.
        configs = {
            config.document_id: config
            for config in NaiveRagDocumentConfig.objects.filter(naive_rag=naive_rag)
        }
        # One embedder made every vector of the RAG, so they all share one length.
        vector_length = None
        for config_entry in entry["document_configs"]:
            config = configs.get(document_ids.get(config_entry["document"]))
            if config is None:
                continue
            for field in _CONFIG_SETTING_FIELDS:
                setattr(config, field, config_entry[field])
            if config_entry["chunks_path"] is not None:
                config.status = config_entry["status"]
                for field in _CONFIG_INDEXED_FIELDS:
                    setattr(config, field, config_entry[field])
                vector_length = self._create_chunks(
                    config, archive, config_entry["chunks_path"], vector_length
                )
            else:
                # No index data came over; the config is new, so its indexed_* are still empty.
                config.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.NEW
            config.save()

        naive_rag.update_rag_status()
        naive_rag.save(update_fields=["rag_status"])
        id_mapper.map(NAIVE_RAG_KEY, entry["id"], naive_rag.naive_rag_id)

    @staticmethod
    def _create_chunks(
        config: NaiveRagDocumentConfig,
        archive: ImportArchive,
        path: str,
        vector_length: int | None,
    ) -> int | None:
        """Insert one config's chunks and vectors in batches; returns the vector length."""
        batch: list[tuple[NaiveRagChunk, list[float] | None]] = []

        def flush() -> None:
            chunks = NaiveRagChunk.objects.bulk_create([chunk for chunk, _ in batch])
            NaiveRagEmbedding.objects.bulk_create(
                [
                    NaiveRagEmbedding(naive_rag_document_config=config, chunk=chunk, vector=vector)
                    for chunk, (_, vector) in zip(chunks, batch, strict=True)
                    if vector is not None
                ]
            )
            batch.clear()

        with archive.open_member(path) as member:
            for line in _iter_lines(member):
                try:
                    row = json.loads(line)
                    vector = row.get("vector")
                    chunk = NaiveRagChunk(
                        naive_rag_document_config=config,
                        **{field: row.get(field) for field in _IMPORTED_CHUNK_FIELDS},
                    )
                except (ValueError, TypeError, AttributeError) as error:
                    raise _refuse(f"{path} holds a line that is not a chunk") from error
                if chunk.text is None or chunk.chunk_index is None:
                    raise _refuse(f"{path} holds a chunk without text or index")
                if chunk.metadata is None:
                    chunk.metadata = {}
                if vector is not None:
                    if vector_length is None:
                        vector_length = len(vector)
                    elif len(vector) != vector_length:
                        raise _refuse("vectors of different lengths in one RAG")
                batch.append((chunk, vector))
                if len(batch) >= _CHUNK_BATCH_SIZE:
                    flush()
        if batch:
            flush()
        return vector_length

    @staticmethod
    def _create_graph_rag(
        entry: dict,
        collection: SourceCollection,
        document_ids: dict[int, int],
        archive: ImportArchive,
        id_mapper: IDMapper,
        created_graph_rag_ids: list[int],
    ) -> None:
        base = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
        )
        index_config = (
            GraphRagIndexConfig.objects.create(**entry["index_config"])
            if entry["index_config"] is not None
            else None
        )
        graph_rag = GraphRag.objects.create(
            base_rag_type=base,
            embedder_id=id_mapper.get_or_none(EntityType.EMBEDDING_CONFIG, entry["embedder"]),
            llm_id=id_mapper.get_or_none(EntityType.LLM_CONFIG, entry["llm"]),
            index_config=index_config,
            slot=GraphRag.Slot.A,
        )
        has_index = entry["artifacts_path"] is not None
        # The index stores the link row's id, so this is the map the restore needs.
        graph_document_ids = {}
        for document_entry in entry["documents"]:
            document_id = document_ids.get(document_entry["document"])
            if document_id is None:
                continue
            graph_document = GraphRagDocument.objects.create(
                graph_rag=graph_rag,
                document_id=document_id,
                status=document_entry["status"] if has_index else GraphRagDocument.Status.NEW,
            )
            graph_document_ids[document_entry["id"]] = graph_document.graph_rag_document_id

        graph_rag.update_rag_status()
        graph_rag.save(update_fields=["rag_status"])
        id_mapper.map(GRAPH_RAG_KEY, entry["id"], graph_rag.graph_rag_id)

        if has_index:
            # Recorded before the upload, so a half-done restore is removed as well.
            created_graph_rag_ids.append(graph_rag.graph_rag_id)
            with (
                archive.open_member(entry["artifacts_path"]) as member,
                KnowledgeClient() as client,
            ):
                client.upload_graph_artifacts(graph_rag.graph_rag_id, member, graph_document_ids)
