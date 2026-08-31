import os

import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import ChunkingError
from domain.models import PreviewChunk
from infrastructure.naive.chunkers.strategies.character_chunker import CharacterChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config


def build_chunker(
    chunk_size: int,
    chunk_overlap: int = 0,
    extra: dict | None = None,
) -> CharacterChunker:
    config = make_config(
        ChunkStrategyEnum.CHARACTER,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        extra=extra or {},
    )
    return CharacterChunker(config)


@pytest.mark.parametrize(
    "regex,text,chunk_size,expected_chunks",
    [
        (
            r"-|,",
            "12345678-qwertyui,ASDFGHJK",
            8,
            ["12345678", "qwertyui", "ASDFGHJK"],
        ),
        (
            r"-|,",
            "12345678-qwertyui,ASDFGHJK",
            4,
            ["1234", "5678", "qwer", "tyui", "ASDF", "GHJK"],
        ),
    ],
)
async def test_chunking_by_regex_without_overlap(regex, text, chunk_size, expected_chunks):
    expected_chunks = [PreviewChunk(text=t) for t in expected_chunks]
    chunker = build_chunker(chunk_size=chunk_size, extra={"character": {"regex": regex}})
    chunks = await chunker.chunk(text)
    assert chunks == expected_chunks


@pytest.mark.parametrize(
    "regex,text,chunk_size,chunk_overlap,expected_chunks",
    [
        (
            r"-|,",
            "12345678-qwertyui,ASDFGHJK",
            8,
            2,
            ["12345678", "qwertyui", "ASDFGHJK"],
        ),
        (
            r"-|,",
            "12345678-qwertyui,ASDFGHJK",
            4,
            2,
            ["1234", "3456", "5678", "qwer", "erty", "tyui", "ASDF", "DFGH", "GHJK"],
        ),
    ],
)
async def test_chunking_by_regex_with_overlap(
    regex,
    text,
    chunk_size,
    chunk_overlap,
    expected_chunks,
):
    expected_chunks = [PreviewChunk(text=t) for t in expected_chunks]
    chunker = build_chunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        extra={"character": {"regex": regex}},
    )
    chunks = await chunker.chunk(text)
    assert chunks == expected_chunks


@pytest.mark.parametrize("text", [None, 0])
async def test_chunking_raises_error_for_invalid_data(text):
    chunker = build_chunker(chunk_size=10, chunk_overlap=0, extra={})
    with pytest.raises(ChunkingError):
        await chunker.chunk(text)


@pytest.mark.parametrize("extra", [{}, {"character": {}}, {"character": {"regex": None}}])
async def test_chunking_uses_default_regexp(extra):
    chunker = build_chunker(chunk_size=4, chunk_overlap=0, extra=extra)
    assert chunker.regex_pattern == r".+"


@pytest.mark.parametrize(
    "text,chunk_size,chunk_overlap,expected_chunk",
    [
        (
            "a",
            4,
            3,
            ["a"],
        ),
        (
            "ab",
            4,
            3,
            ["ab"],
        ),
        ("abc", 4, 3, ["abc"]),
        (
            "abcd",
            4,
            3,
            ["abcd"],
        ),
    ],
)
async def test_short_part_is_kept_as_single_chunk(text, chunk_size, chunk_overlap, expected_chunk):
    chunker = build_chunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        extra={"character": {"regex": ","}},
    )
    chunks = await chunker.chunk(text)
    assert chunks == [PreviewChunk(text=expected_chunk[0])]


async def test_short_part_not_lost_among_normal_parts():
    chunker = build_chunker(chunk_size=4, chunk_overlap=3, extra={"character": {"regex": ","}})
    chunks = await chunker.chunk("ab,cdefgh")
    assert chunks == [PreviewChunk(text=t) for t in ["ab", "cdef", "defg", "efgh"]]


async def test_chunking_is_running_in_process():
    text = "12345678-qwertyui,ASDFGHJK"
    chunker = build_chunker(chunk_size=4, chunk_overlap=2, extra={"character": {"regex": r"-|,"}})
    inline_chunks = await chunker.chunk(text)
    result, worker_pid = await offload_to_process(lambda: chunker.chunk(text))
    assert result == inline_chunks
    assert worker_pid != os.getpid()
