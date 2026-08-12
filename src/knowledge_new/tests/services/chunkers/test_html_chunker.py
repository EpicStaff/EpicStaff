import os

import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import ChunkingError
from domain.models import PreviewChunk
from infrastructure.naive.chunkers.strategies.html_chunker import HTMLChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config

SAMPLE_HTML = "<h1>Title</h1><p>Hello world paragraph.</p><h2>Sub</h2><p>Second section text.</p>"


def build_chunker(
    chunk_size: int = 200, chunk_overlap: int = 0, extra: dict | None = None
) -> HTMLChunker:
    config = make_config(
        ChunkStrategyEnum.HTML,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        extra=extra or {},
    )
    return HTMLChunker(config)


async def test_chunk_prefixes_metadata_when_split_on_headers():
    chunker = build_chunker(extra={"html": {"headers_to_split_on": ["h1", "h2"]}})
    chunks = await chunker.chunk(SAMPLE_HTML)
    assert chunks == [
        PreviewChunk(text="{'Header 1': 'Title'}\nHello world paragraph."),
        PreviewChunk(text="{'Header 2': 'Sub'}\nSecond section text."),
    ]


async def test_chunk_without_headers_has_no_metadata_prefix():
    chunker = build_chunker()
    chunks = await chunker.chunk(SAMPLE_HTML)
    assert chunks == [PreviewChunk(text="Title Hello world paragraph. Sub Second section text.")]


@pytest.mark.parametrize("text", ["", "just plain text with no tags"])
async def test_chunk_returns_empty_for_no_content(text):
    chunker = build_chunker()
    assert await chunker.chunk(text) == []


@pytest.mark.parametrize("text", [None, 0])
async def test_chunking_raises_error_for_invalid_data(text):
    chunker = build_chunker()
    with pytest.raises(ChunkingError):
        await chunker.chunk(text)


async def test_chunking_is_running_in_process():
    chunker = build_chunker(extra={"html": {"headers_to_split_on": ["h1", "h2"]}})

    inline_chunks = await chunker.chunk(SAMPLE_HTML)
    result, worker_pid = await offload_to_process(lambda: chunker.chunk(SAMPLE_HTML))
    assert result == inline_chunks
    assert worker_pid != os.getpid()
