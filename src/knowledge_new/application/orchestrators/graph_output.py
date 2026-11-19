"""Read the tables a GraphRAG index run wrote to its output storage.

The indexer writes each table as `<name>.parquet` through graphrag's default parquet
table provider, so the files are read straight from storage here. That keeps the
download on the event loop (it is async I/O) and moves the CPU-bound parquet decoding
to a worker thread, and it lets a caller decode only the columns it needs.
"""

import asyncio
from collections.abc import Sequence
from io import BytesIO

import pandas
import pyarrow.parquet
from application.ports import AbstractUnitOfWork
from domain.enums import GraphOutputTableEnum
from domain.errors import GraphNotIndexedError, GraphRagConfigNotFoundError
from graphrag_storage import Storage, create_storage

# Every graph index run that gets past graph extraction writes this table, so its
# presence is what tells an indexed graph apart from one that was never indexed.
_INDEX_MARKER_TABLE = GraphOutputTableEnum.ENTITIES


async def open_graph_output_storage(uow: AbstractUnitOfWork, rag_id: int) -> Storage:
    """Return the storage holding the active slot's index output of `rag_id`.

    Raises:
        GraphRagConfigNotFoundError: No graph RAG with this id.
    """
    async with uow:
        storage_config = await uow.graph_rag_repo.get_output_storage_config(rag_id)
    if storage_config is None:
        raise GraphRagConfigNotFoundError(rag_id=rag_id)
    return create_storage(storage_config)


async def ensure_graph_indexed(storage: Storage, rag_id: int) -> None:
    """Fail unless an index run has written the graph's core output.

    Only checks that the file exists; nothing is downloaded. An optional table (such
    as covariates) missing from an indexed graph is not this error.

    Raises:
        GraphNotIndexedError: The graph has no index output yet.
    """
    if not await storage.has(_table_key(_INDEX_MARKER_TABLE)):
        raise GraphNotIndexedError(rag_id=rag_id)


async def read_output_table(
    storage: Storage, table_name: str, columns: Sequence[str]
) -> pandas.DataFrame | None:
    """Return `columns` of one output table, or `None` if the index has not written it.

    A requested column the file does not have is left out of the result; callers that
    need a fixed column set reindex. A file that exists but cannot be decoded raises.
    """
    content = await _download_table(storage, table_name)
    if content is None:
        return None
    return await asyncio.to_thread(_decode_columns, content, columns)


async def count_output_table_rows(storage: Storage, table_name: str) -> int | None:
    """Return the row count of one output table, or `None` if the index has not written it.

    The count comes from the parquet footer, so no column data is decoded. The storage
    API has no ranged reads, so the whole file is still downloaded.
    """
    content = await _download_table(storage, table_name)
    if content is None:
        return None
    return await asyncio.to_thread(_count_rows, content)


def _table_key(table_name: str) -> str:
    return f"{table_name}.parquet"


async def _download_table(storage: Storage, table_name: str) -> bytes | None:
    # Every storage implementation answers `get` for a missing key with None.
    return await storage.get(_table_key(table_name), as_bytes=True)


def _decode_columns(content: bytes, columns: Sequence[str]) -> pandas.DataFrame:
    available_columns = set(pyarrow.parquet.read_schema(BytesIO(content)).names)
    present_columns = [column for column in columns if column in available_columns]
    return pandas.read_parquet(BytesIO(content), columns=present_columns)


def _count_rows(content: bytes) -> int:
    return pyarrow.parquet.ParquetFile(BytesIO(content)).metadata.num_rows
