import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import ChunkingError
from infrastructure.naive.chunkers.strategies.token_chunker import (
    TokenChunker,
    load_token_encoding,
)
from tests.services.chunkers.conftest import make_config

LONG_TEXT = " ".join(f"word{i}" for i in range(40))
UKRAINIAN = "\n\n".join(
    f"Розділ {i}. Олена Коваль керує командою. ґудзик, ґава, їжак, єнот 🤖 日本語." * (i % 4 + 1)
    for i in range(60)
)
NO_SPACES = "ґїєщ👋🤖日語👨‍👩‍👧" * 400


def build_chunker(chunk_size: int, chunk_overlap: int) -> TokenChunker:
    config = make_config(
        ChunkStrategyEnum.TOKEN,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return TokenChunker(config)


def reassemble(chunks):
    """Join chunks, dropping each chunk's overlap with the previous one."""
    text = chunks[0].text
    for chunk in chunks[1:]:
        text += chunk.text[chunk.overlap_start :]
    return text


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


@pytest.mark.parametrize("text", ["", "  \n \t "], ids=["empty", "whitespace"])
async def test_text_without_content_returns_empty(text):
    chunker = build_chunker(chunk_size=10, chunk_overlap=3)
    assert await chunker.chunk(text) == []


@pytest.mark.parametrize("chunk_size,chunk_overlap", [(20, 19), (500, 499)])
async def test_one_token_step_does_not_repeat_a_chunk(chunk_size, chunk_overlap):
    text = "👋🤖𝔘𝔨𝔯" * 300  # four-byte characters, each several tokens long
    chunks = await build_chunker(chunk_size, chunk_overlap).chunk(text)
    assert not any(
        previous.text.endswith(current.text) for previous, current in zip(chunks, chunks[1:])
    )
    assert reassemble(chunks) == text


@pytest.mark.parametrize("text", [UKRAINIAN, NO_SPACES], ids=["ukrainian", "no-spaces"])
@pytest.mark.parametrize("chunk_size,chunk_overlap", [(1000, 150), (32, 8), (20, 0)])
async def test_multibyte_text_is_kept_whole(text, chunk_size, chunk_overlap):
    chunks = await build_chunker(chunk_size, chunk_overlap).chunk(text)
    assert all("\ufffd" not in c.text and c.text for c in chunks)
    assert reassemble(chunks) == text


async def test_overlap_counts_are_the_shared_text():
    chunks = await build_chunker(32, 8).chunk(UKRAINIAN)
    for previous, current in zip(chunks, chunks[1:]):
        assert previous.overlap_end == current.overlap_start
        assert (
            previous.text[len(previous.text) - previous.overlap_end :]
            == current.text[: current.overlap_start]
        )


async def test_token_count_is_the_chunk_text_token_count():
    encoding = load_token_encoding()
    chunks = await build_chunker(32, 8).chunk(UKRAINIAN)
    assert all(c.token_count == len(encoding.encode_ordinary(c.text)) for c in chunks)
    # A cut moved back to a character start adds at most a few tokens on this text.
    assert max(c.token_count for c in chunks) <= 32 + 2


async def test_special_token_strings_are_plain_text():
    text = "Текст <|endoftext|> і <|fim_prefix|> всередині. " * 20
    chunks = await build_chunker(32, 8).chunk(text)
    assert reassemble(chunks) == text


@pytest.mark.parametrize("chunk_overlap", [10, 11])
async def test_overlap_not_smaller_than_size_raises_chunking_error(chunk_overlap):
    with pytest.raises(ChunkingError):
        await build_chunker(chunk_size=10, chunk_overlap=chunk_overlap).chunk("hello world")
