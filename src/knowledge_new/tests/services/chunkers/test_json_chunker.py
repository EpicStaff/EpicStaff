import json
import os

import pytest
from domain.enums import ChunkStrategyEnum
from domain.errors import ChunkingError
from domain.models import PreviewChunk
from infrastructure.naive.chunkers.strategies.json_chunker import JSONChunker
from tests.conftest import offload_to_process
from tests.services.chunkers.conftest import make_config


def build_chunker(chunk_size: int = 200, chunk_overlap: int = 0) -> JSONChunker:
    config = make_config(ChunkStrategyEnum.JSON, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return JSONChunker(config)


async def test_small_object_is_one_chunk():
    chunker = build_chunker()
    chunks = await chunker.chunk('{"a": 1, "b": 2}')
    assert chunks == [PreviewChunk(text='{"a": 1, "b": 2}')]


async def test_large_object_splits_into_valid_json_chunks():
    data = {f"k{i}": f"value-number-{i}" for i in range(20)}
    chunker = build_chunker(chunk_size=80)
    chunks = await chunker.chunk(json.dumps(data))
    assert len(chunks) > 1
    assert all(isinstance(json.loads(c.text), dict) for c in chunks)


async def test_top_level_array_returns_empty():
    chunker = build_chunker()
    assert await chunker.chunk("[1, 2, 3]") == []


@pytest.mark.parametrize("text", ["", "hello", "{not valid", None, 0])
async def test_chunking_raises_error_for_invalid_data(text):
    chunker = build_chunker()
    with pytest.raises(ChunkingError):
        await chunker.chunk(text)


async def test_chunking_is_running_in_process():
    text = '{"a": 1, "b": 2}'
    chunker = build_chunker()

    inline_chunks = await chunker.chunk(text)
    result, worker_pid = await offload_to_process(lambda: chunker.chunk(text))
    assert result == inline_chunks
    assert worker_pid != os.getpid()
