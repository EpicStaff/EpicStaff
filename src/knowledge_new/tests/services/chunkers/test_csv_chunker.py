import os

import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import ChunkingError
from domain.models import PreviewChunk
from infrastructure.naive.chunkers.strategies.csv_chunker import CSVChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config


def build_chunker(
    file_name: str | None = None,
    headers_level: int = 1,
    rows_in_chunk: int = 150,
) -> CSVChunker:
    config = make_config(
        ChunkStrategyEnum.CSV,
        extra={
            "file_name": file_name,
            "csv": {"headers_level": headers_level, "rows_in_chunk": rows_in_chunk},
        },
    )
    return CSVChunker(config)


async def test_batches_rows_and_repeats_header_with_file_name():
    text = "h1,h2\na,b\nc,d\ne,f"
    chunker = build_chunker(file_name="t.csv", rows_in_chunk=2)
    chunks = await chunker.chunk(text)
    assert chunks == [
        PreviewChunk(text="File name: t.csv\n\nh1,h2\na,b\nc,d"),
        PreviewChunk(text="File name: t.csv\n\nh1,h2\ne,f"),
    ]


async def test_defaults_single_chunk_with_none_file_name():
    text = "h1,h2\na,b\nc,d\ne,f"
    chunker = build_chunker()
    chunks = await chunker.chunk(text)
    assert chunks == [PreviewChunk(text="File name: undefined\n\nh1,h2\na,b\nc,d\ne,f")]


async def test_headers_level_repeats_multiple_header_lines():
    text = "h1,h2\na,b\nc,d\ne,f"
    chunker = build_chunker(headers_level=2, rows_in_chunk=1)
    chunks = await chunker.chunk(text)
    assert chunks == [
        PreviewChunk(text="File name: undefined\n\nh1,h2\na,b\nc,d"),
        PreviewChunk(text="File name: undefined\n\nh1,h2\na,b\ne,f"),
    ]


@pytest.mark.parametrize(
    "data_rows,rows_in_chunk,expected_chunks",
    [
        (
            0,
            2,
            0,
        ),
        (
            1,
            2,
            1,
        ),
        (
            2,
            2,
            1,
        ),
        (
            3,
            2,
            2,
        ),
        (
            4,
            2,
            2,
        ),
        (
            5,
            2,
            3,
        ),
    ],
)
async def test_number_of_chunks_follows_ceil(data_rows, rows_in_chunk, expected_chunks):
    rows = [f"r{i},v{i}" for i in range(data_rows)]
    text = "\n".join(["h1,h2", *rows])
    chunker = build_chunker(rows_in_chunk=rows_in_chunk)
    chunks = await chunker.chunk(text)
    assert len(chunks) == expected_chunks


@pytest.mark.parametrize("text", ["", "   ", "h1,h2"])
async def test_no_data_rows_returns_empty(text):
    chunker = build_chunker()
    chunks = await chunker.chunk(text)
    assert chunks == []


@pytest.mark.parametrize("text", [None, 0])
async def test_chunking_raises_error_for_invalid_data(text):
    chunker = build_chunker()
    with pytest.raises(ChunkingError):
        await chunker.chunk(text)


async def test_chunking_is_running_in_process():
    text = "h1,h2\na,b\nc,d\ne,f"
    chunker = build_chunker(file_name="t.csv", rows_in_chunk=2)

    inline_chunks = await chunker.chunk(text)
    result, worker_pid = await offload_to_process(lambda: chunker.chunk(text))
    assert result == inline_chunks
    assert worker_pid != os.getpid()
