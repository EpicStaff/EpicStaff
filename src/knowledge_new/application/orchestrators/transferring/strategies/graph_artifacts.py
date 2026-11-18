import tarfile
import tempfile
from collections.abc import Mapping
from pathlib import Path

import anyio
import pyarrow as pa
import pyarrow.parquet as pq
from application.commands import (
    ExportGraphArtifacts,
    RestoreGraphArtifacts,
    RewriteGraphDocumentIds,
)
from application.orchestrators.transferring.base import (
    AbstractArtifactExportOrchestrator,
    AbstractArtifactRestoreOrchestrator,
    AbstractDocumentIdRewriteOrchestrator,
)
from application.results import ArtifactExportResult
from domain.enums import IndexStatusEnum, SlotEnum
from domain.errors import (
    GraphArtifactsNotReadyError,
    InvalidArtifactArchiveError,
    RagInProcessingError,
    RagNotFoundError,
)
from infrastructure.graphrag.artifact_tar import open_artifact_tar, read_members, stream_tar
from infrastructure.graphrag.document_id_rewrite import DocumentIdRewriter

# Slot folders that make up an index; `update_output/` only holds a run's scratch data.
_EXPORTED_FOLDERS = frozenset({"input", "lancedb", "output"})
# The two tables that hold our `GraphRagDocument` ids, and the column holding them.
_DOCUMENT_ID_TABLES = (
    ("output/documents.parquet", "id"),
    ("output/text_units.parquet", "document_id"),
)
# Django creates an imported RAG with this slot, so a restore always writes to it.
_RESTORE_SLOT = SlotEnum.A
# Rows one document may have in a rewritten table: documents.parquet holds one per
# document, text_units.parquet one per chunk. 100 000 chunks of the default 1200 tokens is
# about half a GB of text in one document. Scaled by the documents Django sends, so a small
# collection cannot carry a huge table: parquet compresses a repeated value to almost
# nothing, so the row count, not the file size, bounds the work.
_MAX_ROWS_PER_DOCUMENT = 100_000
# Rows rewritten at once; a text unit row carries its chunk text, so this bounds memory.
_REWRITE_BATCH_ROWS = 10_000


def _rag_prefix(rag_id: int) -> str:
    return f"graphrag/rag_{rag_id}/"


def _slot_prefix(rag_id: int, slot: SlotEnum) -> str:
    return f"{_rag_prefix(rag_id)}{slot}/"


class GraphArtifactExportOrchestrator(AbstractArtifactExportOrchestrator):
    async def on_execute(self, command: ExportGraphArtifacts) -> ArtifactExportResult:
        async with self.uow:
            rag = await self.uow.graph_rag_repo.get_rag(command.rag_id)

        # Every check runs here, before the first byte is streamed: once the response
        # has started, an error can no longer change its status code.
        if rag is None:
            raise RagNotFoundError(rag_id=command.rag_id)
        if rag.status == IndexStatusEnum.PROCESSING:
            raise RagInProcessingError(f"RAG(id={command.rag_id}) is being indexed.")
        if rag.status != IndexStatusEnum.COMPLETED or rag.slot is None:
            raise GraphArtifactsNotReadyError(rag_id=command.rag_id)

        slot_prefix = _slot_prefix(command.rag_id, rag.slot)
        members = []
        for stored in await self.artifact_store.list_objects(slot_prefix):
            name = stored.key.removeprefix(slot_prefix)
            if name.split("/", 1)[0] in _EXPORTED_FOLDERS:
                members.append((name, stored))

        # Without them the import refuses the tar, so refuse to produce it.
        names = {name for name, _ in members}
        if any(table not in names for table, _ in _DOCUMENT_ID_TABLES):
            raise GraphArtifactsNotReadyError(rag_id=command.rag_id)

        return ArtifactExportResult(stream=stream_tar(self.artifact_store, members))


class GraphArtifactRestoreOrchestrator(AbstractArtifactRestoreOrchestrator):
    """Write an exported tar into slot `a/` of a RAG.

    It never reads the database: Django calls it inside its import transaction, so
    the RAG row is not committed yet and this service cannot see it.
    """

    async def on_execute(self, command: RestoreGraphArtifacts) -> None:
        rag_prefix = _rag_prefix(command.rag_id)
        slot_prefix = _slot_prefix(command.rag_id, _RESTORE_SLOT)
        # tarfile reads the temp file synchronously inside the event loop. Accepted:
        # the endpoint is internal and rare, and miniopy reads `source` synchronously too.
        try:
            with open_artifact_tar(command.archive_path) as tar:
                # Validate every member before deleting or writing anything.
                members = read_members(tar)
                await self.artifact_store.clear(rag_prefix)
                for member in members:
                    await self.artifact_store.put(
                        f"{slot_prefix}{member.name}", tar.extractfile(member), member.size
                    )
        except tarfile.TarError as error:
            raise InvalidArtifactArchiveError(reason=f"not a readable tar ({error})") from error

    async def on_error(self, command: RestoreGraphArtifacts, error: Exception) -> None:
        await self.artifact_store.clear(_rag_prefix(command.rag_id))

    async def on_cancel(self, command: RestoreGraphArtifacts) -> None:
        await self.artifact_store.clear(_rag_prefix(command.rag_id))


class GraphDocumentIdRewriteOrchestrator(AbstractDocumentIdRewriteOrchestrator):
    """Replace the old document ids in a restored index with the new ones.

    It never reads the database, for the same reason as the restore. On failure it
    leaves the files as they are: Django then deletes the whole RAG.
    """

    async def on_execute(self, command: RewriteGraphDocumentIds) -> None:
        slot_prefix = _slot_prefix(command.rag_id, _RESTORE_SLOT)

        keys = {stored.key for stored in await self.artifact_store.list_objects(slot_prefix)}
        if any(f"{slot_prefix}{table}" not in keys for table, _ in _DOCUMENT_ID_TABLES):
            raise GraphArtifactsNotReadyError(rag_id=command.rag_id)

        # Rewrite both tables before uploading either, so an unknown id in the second
        # one leaves the first unchanged. Each table goes through temp files, so the
        # bytes of a large table are never held in memory.
        with tempfile.TemporaryDirectory(prefix="graph-rewrite-") as directory:
            rewritten: list[tuple[str, Path]] = []
            for position, (table_name, column) in enumerate(_DOCUMENT_ID_TABLES):
                key = f"{slot_prefix}{table_name}"
                original = Path(directory, f"{position}-original.parquet")
                output = Path(directory, f"{position}-rewritten.parquet")
                await self._download(key, original)
                await anyio.to_thread.run_sync(
                    _rewrite_table_file,
                    original,
                    output,
                    table_name,
                    column,
                    command.document_id_map,
                )
                await anyio.Path(original).unlink()
                rewritten.append((key, output))

            for key, path in rewritten:
                await self._upload(key, path)

    async def _download(self, key: str, path: Path) -> None:
        async with await anyio.open_file(path, "wb") as file:
            async for chunk in self.artifact_store.iter_object(key):
                await file.write(chunk)

    async def _upload(self, key: str, path: Path) -> None:
        size = (await anyio.Path(path).stat()).st_size
        async with await anyio.open_file(path, "rb") as file:
            # The store reads a plain binary stream, as the restore hands it a tar member.
            await self.artifact_store.put(key, file.wrapped, size)


def _rewrite_table_file(
    source: Path,
    destination: Path,
    table_name: str,
    column: str,
    document_id_map: Mapping[str, int],
) -> None:
    """Write `source` to `destination` with the document ids in `column` rewritten.

    The row count comes from the parquet footer and is checked before any row is
    read; the rows are then streamed in batches, so only one batch is in memory.
    On a refused id `destination` is left half written: the caller discards it.

    Raises:
        InvalidArtifactArchiveError: The table has more rows than the documents in
            the map can account for, or holds an id the map lacks.
    """
    max_rows = len(document_id_map) * _MAX_ROWS_PER_DOCUMENT
    with pq.ParquetFile(source) as parquet_file:
        if parquet_file.metadata.num_rows > max_rows:
            raise InvalidArtifactArchiveError(
                reason=f"{table_name} has more than {max_rows} rows for {len(document_id_map)} documents"
            )
        rewriter = DocumentIdRewriter(document_id_map)
        with pq.ParquetWriter(destination, parquet_file.schema_arrow) as writer:
            for batch in parquet_file.iter_batches(batch_size=_REWRITE_BATCH_ROWS):
                writer.write_table(rewriter.rewrite(pa.Table.from_batches([batch]), column))
