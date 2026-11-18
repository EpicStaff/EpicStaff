"""Export and import of a knowledge collection with its documents and index data."""

import json
import re
import tempfile
from collections import Counter, defaultdict

from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from rbac.authorship.policy import resolve_author
from rest_framework.exceptions import ValidationError
from src.shared.enums.knowledge_new import RAGStrategy
from utils.exception_handler import flatten_error_detail
from utils.logger import logger

from tables.clients.knowledge import ARTIFACT_TIMEOUT, KnowledgeClient
from tables.exceptions import DocumentUploadException
from tables.import_export.archive import ExportArchiveWriter, ImportArchive, invalid_archive
from tables.import_export.constants import MAX_REUSE_CANDIDATES
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.source_collection import (
    GraphRagIndexConfigExportSerializer,
    SourceCollectionExportSerializer,
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
from tables.models.knowledge_models.collection_models import is_bare_file_name
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)

# Rows read or written per database round trip; a collection can hold hundreds of
# thousands of chunks, so they are never all in memory at once.
_BATCH_SIZE = 1000
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
# Graph document statuses that describe index data which travelled; any other value
# in a file means nothing is indexed.
_INDEXED_GRAPH_DOCUMENT_STATUSES = frozenset(
    {GraphRagDocument.Status.COMPLETED, GraphRagDocument.Status.FAILED}
)
_LINE_READ_SIZE = 1024 * 1024
# One line of a chunks file is one chunk with its vector: a chunk size of at most 8000
# tokens or characters plus a few thousand floats stays well under 1 MiB, even with every
# character escaped. A longer line is refused before it is parsed.
_MAX_LINE_SIZE = 4 * 1024 * 1024
# IDMapper keys for the RAGs inside a collection; knowledge links remap rag ids through them.
NAIVE_RAG_KEY = "NaiveRag"
GRAPH_RAG_KEY = "GraphRag"
RAG_KEYS = {BaseRagType.RagType.NAIVE: NAIVE_RAG_KEY, BaseRagType.RagType.GRAPH: GRAPH_RAG_KEY}

# (count of each (file name, file size), set of RAG types)
_ReuseKey = tuple[Counter, frozenset]


class CollectionChangedError(ValidationError):
    """The collection changed while it was exported; exporting it again will work."""


def _collection_changed(reason: str) -> CollectionChangedError:
    return CollectionChangedError({"code": "collection_changed", "detail": reason})


def remove_restored_graph_indexes(graph_rag_ids: list[int]) -> None:
    """Delete graph indexes an import restored before it rolled back.

    Best effort: the import has already failed and must report that failure,
    not a failed cleanup. Deleting a large index takes a while, so it gets the
    same time an artifact transfer gets.
    """
    if not graph_rag_ids:
        return
    with KnowledgeClient(timeout=ARTIFACT_TIMEOUT) as client:
        for rag_id in graph_rag_ids:
            try:
                client.delete(RAGStrategy.GRAPH, rag_id)
            except Exception:
                logger.exception("Could not remove restored graph index {}", rag_id)


def _iter_lines(member, name: str):
    """Yield the lines of a member without holding it whole in memory.

    Raises:
        InvalidArchiveError: A line of member `name` is longer than `_MAX_LINE_SIZE`.
    """
    pending = b""
    while chunk := member.read(_LINE_READ_SIZE):
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            _ensure_line_size(line, name)
            yield line
        # A member without line breaks is refused here, never accumulated whole.
        _ensure_line_size(pending, name)
    if pending:
        yield pending


def _ensure_line_size(line: bytes, name: str) -> None:
    if len(line) > _MAX_LINE_SIZE:
        raise invalid_archive(f"{name} holds a line longer than {_MAX_LINE_SIZE} bytes")


def _is_non_negative_int(value) -> bool:
    # bool is an int subclass; the columns this checks are positive integers.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


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

    # --- archive files ------------------------------------------------------------------

    def write_archive_members(self, entry: dict, writer: ExportArchiveWriter) -> None:
        """Write every file the exported `entry` points to into the archive.

        The files follow the entry itself, not the collection as it is now, so the
        archive holds exactly what `export.json` names. Nothing larger than one
        document is held in memory.

        Raises:
            CollectionChangedError: Something the entry points to changed or went
                away since the entry was made; exporting again will work.
        """
        self._write_documents(entry, writer)
        self._write_naive_chunks(entry, writer)
        self._write_graph_artifacts(entry, writer)

    @staticmethod
    def _write_documents(entry: dict, writer: ExportArchiveWriter) -> None:
        for document in entry["documents"]:
            if document["content_path"] is None:
                continue
            content = (
                DocumentContent.objects.filter(metadata_records__document_id=document["id"])
                .values_list("content", flat=True)
                .first()
            )
            if content is None:
                raise _collection_changed(f"document {document['file_name']!r} is gone")
            writer.add_bytes(document["content_path"], bytes(content))

    @staticmethod
    def _write_naive_chunks(entry: dict, writer: ExportArchiveWriter) -> None:
        for naive_rag in entry["naive_rags"]:
            for config in naive_rag["document_configs"]:
                if config["chunks_path"] is None:
                    continue
                if not NaiveRagDocumentConfig.objects.filter(
                    pk=config["id"],
                    status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED,
                ).exists():
                    raise _collection_changed("a document was re-indexed during the export")
                with tempfile.TemporaryFile() as lines:
                    rows = (
                        NaiveRagChunk.objects.filter(naive_rag_document_config_id=config["id"])
                        .order_by("chunk_index")
                        .values_list(*_CHUNK_FIELDS)
                        .iterator(chunk_size=_BATCH_SIZE)
                    )
                    for row in rows:
                        chunk = dict(zip(_CHUNK_FIELDS, row, strict=True))
                        vector = chunk.pop("embedding__vector")
                        chunk["vector"] = vector.tolist() if vector is not None else None
                        lines.write(json.dumps(chunk).encode() + b"\n")
                    lines.seek(0)
                    writer.add_file(config["chunks_path"], lines)

    @staticmethod
    def _write_graph_artifacts(entry: dict, writer: ExportArchiveWriter) -> None:
        graph_rags = [rag for rag in entry["graph_rags"] if rag["artifacts_path"] is not None]
        if not graph_rags:
            return
        with KnowledgeClient() as client:
            for graph_rag in graph_rags:
                with tempfile.TemporaryFile() as tar:
                    # The knowledge service refuses an index that is being rebuilt.
                    client.download_graph_artifacts(graph_rag["id"], tar)
                    tar.seek(0)
                    writer.add_file(graph_rag["artifacts_path"], tar)

    # --- reuse --------------------------------------------------------------------------

    def find_existing(
        self, data: dict, id_mapper: IDMapper, org_id: int | None = None
    ) -> SourceCollection | None:
        """Reuse a collection with the same name (or a renamed copy of it), description,
        files and RAG types, in the importing organization only."""
        if org_id is None:
            # A collection belongs to an organization; without one there is nothing to reuse.
            return None
        name = data["collection_name"]
        # Counted in a subquery: the default manager leaves binned documents out, which
        # a Count over the reverse relation would not.
        live_document_count = Coalesce(
            Subquery(
                DocumentMetadata.objects.filter(source_collection=OuterRef("pk"))
                .order_by()
                .values("source_collection")
                .annotate(count=Count("pk"))
                .values("count"),
                output_field=IntegerField(),
            ),
            Value(0),
        )
        # A name clash on save is renamed to "Name (1)", "Name (2)" and so on.
        candidates = list(
            SourceCollection.objects.filter(
                self.get_org_scope_q(org_id), description=data["description"]
            )
            .filter(
                Q(collection_name=name) | Q(collection_name__regex=rf"^{re.escape(name)} \(\d+\)$")
            )
            .annotate(
                is_renamed_copy=Case(
                    When(collection_name=name, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                ),
                document_count=live_document_count,
            )
            .filter(document_count=len(data["documents"]))
            .order_by("is_renamed_copy", "-collection_id")[:MAX_REUSE_CANDIDATES]
        )
        if not candidates:
            return None

        wanted = self._reuse_key_of_entry(data)
        keys = self._reuse_keys_of_collections([candidate.pk for candidate in candidates])
        for candidate in candidates:
            if keys[candidate.pk] == wanted:
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
    def _reuse_keys_of_collections(collection_ids: list[int]) -> dict[int, _ReuseKey]:
        """The reuse key of each collection, in two queries however many there are."""
        files = defaultdict(Counter)
        for collection_id, file_name, file_size in DocumentMetadata.objects.filter(
            source_collection_id__in=collection_ids
        ).values_list("source_collection_id", "file_name", "file_size"):
            files[collection_id][(file_name, file_size)] += 1
        rag_types = defaultdict(set)
        for collection_id, rag_type in BaseRagType.objects.filter(
            source_collection_id__in=collection_ids
        ).values_list("source_collection_id", "rag_type"):
            rag_types[collection_id].add(rag_type)
        return {
            collection_id: (files[collection_id], frozenset(rag_types[collection_id]))
            for collection_id in collection_ids
        }

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

    # --- create -------------------------------------------------------------------------

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
        """Create every document; returns old document id -> new.

        Each document passes the checks an upload passes (plain file name, allowed
        type, size) before its bytes are read; one content row is held at a time.
        """
        rows = []
        document_ids_seen = set()
        for entry in documents:
            file_name = entry["file_name"]
            if not is_bare_file_name(file_name):
                raise invalid_archive(f"document name {file_name!r} is a path")
            if entry["id"] in document_ids_seen:
                raise invalid_archive(f"document {entry['id']} appears twice")
            document_ids_seen.add(entry["id"])
            content_id = None
            if entry["content_path"] is not None:
                file_size = archive.member_size(entry["content_path"])
            else:
                file_size = entry["file_size"]
                # A document without content may have no recorded size, as the model allows.
                if file_size is not None and not _is_non_negative_int(file_size):
                    raise invalid_archive(f"document {file_name!r} has no valid file size")
            try:
                metadata = DocumentManagementService.validate_file_metadata(
                    file_name, file_size or 0
                )
            except DocumentUploadException as error:
                raise invalid_archive(str(error.detail)) from error
            if entry["content_path"] is not None:
                # Only the id is kept: the row object would hold the bytes until the end.
                with archive.open_member(entry["content_path"]) as member:
                    content_id = DocumentContent.objects.create(content=member.read()).pk
            rows.append(
                (
                    entry["id"],
                    DocumentMetadata(
                        source_collection=collection,
                        document_content_id=content_id,
                        file_name=file_name,
                        file_type=metadata["file_type"],
                        file_size=file_size,
                    ),
                )
            )
        # bulk_create skips DocumentMetadata.save(); its name check ran above, and the
        # collection status it updates is set once by the caller.
        created = DocumentMetadata.objects.bulk_create(
            [document for _, document in rows], batch_size=_BATCH_SIZE
        )
        return {
            old_id: document.document_id
            for (old_id, _), document in zip(rows, created, strict=True)
        }

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
        # The signal that adds them logs its failures instead of raising; a document
        # without its config would lose its chunks without a word.
        if set(configs) != set(document_ids.values()):
            raise ValidationError(
                {"code": "import_failed", "detail": "Could not prepare the collection's documents."}
            )
        # One embedder made every vector of the RAG, so they all share one length.
        vector_length = None
        filled = {}
        for config_entry in entry["document_configs"]:
            config = configs.get(document_ids.get(config_entry["document"]))
            if config is None:
                continue
            if config.pk in filled:
                raise invalid_archive(f"document {config_entry['document']} is configured twice")
            for field in _CONFIG_SETTING_FIELDS:
                setattr(config, field, config_entry[field])
            if config_entry["chunks_path"] is not None:
                # Index data travelled: the config is indexed, whatever status the file says.
                config.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED
                for field in _CONFIG_INDEXED_FIELDS:
                    setattr(config, field, config_entry[field])
                vector_length = self._create_chunks(
                    config, archive, config_entry["chunks_path"], vector_length
                )
            else:
                # No index data came over; the config is new, so its indexed_* are still empty.
                config.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.NEW
            filled[config.pk] = config
        NaiveRagDocumentConfig.objects.bulk_update(
            filled.values(),
            fields=[*_CONFIG_SETTING_FIELDS, "status", *_CONFIG_INDEXED_FIELDS],
            batch_size=_BATCH_SIZE,
        )

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
        # Two chunks at one index break a unique constraint; refused here instead.
        seen_indexes: set[int] = set()

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
            for line in _iter_lines(member, path):
                try:
                    row = json.loads(line)
                    vector = row.get("vector")
                    chunk = NaiveRagChunk(
                        naive_rag_document_config=config,
                        **{field: row.get(field) for field in _IMPORTED_CHUNK_FIELDS},
                    )
                except (ValueError, TypeError, AttributeError) as error:
                    raise invalid_archive(f"{path} holds a line that is not a chunk") from error
                if not isinstance(chunk.text, str) or not _is_non_negative_int(chunk.chunk_index):
                    raise invalid_archive(f"{path} holds a chunk without text or index")
                if vector is not None and not isinstance(vector, list):
                    raise invalid_archive(f"{path} holds a vector that is not a list")
                if chunk.chunk_index in seen_indexes:
                    raise invalid_archive(f"{path} holds chunk {chunk.chunk_index} twice")
                seen_indexes.add(chunk.chunk_index)
                if chunk.metadata is None:
                    chunk.metadata = {}
                if vector is not None:
                    if vector_length is None:
                        vector_length = len(vector)
                    elif len(vector) != vector_length:
                        raise invalid_archive("vectors of different lengths in one RAG")
                batch.append((chunk, vector))
                if len(batch) >= _BATCH_SIZE:
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
        index_config = None
        if entry["index_config"] is not None:
            # The serializer's fields are the whole whitelist; other keys are ignored.
            config = GraphRagIndexConfigExportSerializer(data=entry["index_config"])
            if not config.is_valid():
                raise invalid_archive(
                    f"graph RAG {entry['id']} has an invalid index config: "
                    f"{flatten_error_detail(config.errors)}"
                )
            index_config = GraphRagIndexConfig.objects.create(**config.validated_data)
        graph_rag = GraphRag.objects.create(
            base_rag_type=base,
            embedder_id=id_mapper.get_or_none(EntityType.EMBEDDING_CONFIG, entry["embedder"]),
            llm_id=id_mapper.get_or_none(EntityType.LLM_CONFIG, entry["llm"]),
            index_config=index_config,
            slot=GraphRag.Slot.A,
        )
        has_index = entry["artifacts_path"] is not None

        links = []
        linked_document_ids = set()
        for document_entry in entry["documents"]:
            document_id = document_ids.get(document_entry["document"])
            if document_id is None:
                continue
            if document_id in linked_document_ids:
                raise invalid_archive(
                    f"document {document_entry['document']} is linked to a graph RAG twice"
                )
            linked_document_ids.add(document_id)
            status = document_entry["status"]
            if not has_index or status not in _INDEXED_GRAPH_DOCUMENT_STATUSES:
                status = GraphRagDocument.Status.NEW
            links.append(
                (
                    document_entry["id"],
                    GraphRagDocument(graph_rag=graph_rag, document_id=document_id, status=status),
                )
            )
        created = GraphRagDocument.objects.bulk_create(
            [link for _, link in links], batch_size=_BATCH_SIZE
        )
        # The index stores the link row's id, so this is the map the restore needs.
        graph_document_ids = {
            old_id: link.graph_rag_document_id
            for (old_id, _), link in zip(links, created, strict=True)
        }

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
