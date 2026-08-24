import os

import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import ChunkingError
from infrastructure.naive.chunkers.strategies.token_chunker import TokenChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config

LONG_TEXT = " ".join(f"word{i}" for i in range(40))


def build_chunker(chunk_size: int, chunk_overlap: int) -> TokenChunker:
    config = make_config(
        ChunkStrategyEnum.TOKEN,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return TokenChunker(config)


async def test_single_chunk_has_token_count_and_no_overlap():
    chunker = build_chunker(chunk_size=100, chunk_overlap=10)
    chunks = await chunker.chunk("hello world")
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].token_count == 2
    assert chunks[0].overlap_start is None
    assert chunks[0].overlap_end is None


@pytest.mark.parametrize(
    "chunk_size,chunk_overlap",
    [
        (
            10,
            3,
        ),
        (
            8,
            2,
        ),
        (
            15,
            5,
        ),
    ],
)
async def test_multi_chunk_overlap_edges_and_invariant(chunk_size, chunk_overlap):
    chunker = build_chunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = await chunker.chunk(LONG_TEXT)
    assert len(chunks) > 1
    assert all(c.token_count and c.token_count > 0 for c in chunks)
    assert chunks[0].overlap_start is None
    assert chunks[-1].overlap_end is None
    assert all(chunks[i].overlap_end == chunks[i + 1].overlap_start for i in range(len(chunks) - 1))


async def test_empty_string_returns_empty():
    chunker = build_chunker(chunk_size=10, chunk_overlap=3)
    assert await chunker.chunk("") == []


@pytest.mark.parametrize("text", [None, 0])
async def test_chunking_raises_error_for_invalid_data(text):
    chunker = build_chunker(chunk_size=10, chunk_overlap=3)
    with pytest.raises(ChunkingError):
        await chunker.chunk(text)


async def test_chunking_is_running_in_process():
    chunker = build_chunker(chunk_size=10, chunk_overlap=3)

    inline_chunks = await chunker.chunk(LONG_TEXT)
    result, worker_pid = await offload_to_process(lambda: chunker.chunk(LONG_TEXT))
    assert result == inline_chunks
    assert worker_pid != os.getpid()
