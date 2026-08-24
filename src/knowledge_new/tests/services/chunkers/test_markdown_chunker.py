import os

import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import ChunkingError
from domain.models import PreviewChunk
from infrastructure.naive.chunkers.strategies.markdown_chunker import MarkdownChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config

SAMPLE_MD = "# Title\nIntro text.\n## Section\nSection body text here."


def build_chunker(
    chunk_size: int = 200, chunk_overlap: int = 0, extra: dict | None = None
) -> MarkdownChunker:
    config = make_config(
        ChunkStrategyEnum.MARKDOWN,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        extra=extra or {},
    )
    return MarkdownChunker(config)


async def test_header_split_keeps_header_in_each_section():
    chunker = build_chunker(extra={"markdown": {"headers_to_split_on": ["#", "##"]}})
    chunks = await chunker.chunk(SAMPLE_MD)
    assert chunks == [
        PreviewChunk(text="# Title\nIntro text."),
        PreviewChunk(text="## Section\nSection body text here."),
    ]


async def test_no_headers_config_returns_single_chunk():
    chunker = build_chunker()
    chunks = await chunker.chunk(SAMPLE_MD)
    assert chunks == [PreviewChunk(text=SAMPLE_MD)]


async def test_long_section_is_split_by_char_size():
    body = " ".join(f"word{i}" for i in range(60))
    chunker = build_chunker(chunk_size=50, extra={"markdown": {"headers_to_split_on": ["#"]}})
    chunks = await chunker.chunk(f"# Title\n{body}")
    assert len(chunks) > 1
    assert all(len(c.text) <= 50 for c in chunks)


async def test_empty_string_returns_empty():
    chunker = build_chunker()
    assert await chunker.chunk("") == []


@pytest.mark.parametrize("text", [None, 0])
async def test_chunking_raises_error_for_invalid_data(text):
    chunker = build_chunker()
    with pytest.raises(ChunkingError):
        await chunker.chunk(text)


async def test_chunking_is_running_in_process():
    chunker = build_chunker(extra={"markdown": {"headers_to_split_on": ["#", "##"]}})

    inline_chunks = await chunker.chunk(SAMPLE_MD)
    result, worker_pid = await offload_to_process(lambda: chunker.chunk(SAMPLE_MD))
    assert result == inline_chunks
    assert worker_pid != os.getpid()
