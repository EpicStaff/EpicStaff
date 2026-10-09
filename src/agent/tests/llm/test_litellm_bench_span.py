import asyncio
import io
import json
import sys

import pytest
from loguru import logger
from shared.bench_log import add_bench_sink, without_bench

from app.llm.client import LLMChunk
from app.llm.litellm_client import _bench_llm_span


@pytest.fixture(autouse=True)
def _restore_logger():
    yield
    logger.remove()
    logger.add(sys.stderr)


async def _chunks(fail: bool):
    yield LLMChunk(delta_text="hi")
    yield LLMChunk(usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "total_cost_usd": 0.001})
    if fail:
        raise RuntimeError("rate limited")


def _bench_lines(fail: bool) -> list[dict]:
    stream = io.StringIO()
    logger.remove()
    logger.add(stream, level="BENCH", format="{message}", filter=without_bench())
    add_bench_sink(stream, "BENCH")

    async def consume():
        return [chunk async for chunk in _bench_llm_span(_chunks(fail), "gpt-4o-mini")]

    if fail:
        with pytest.raises(RuntimeError):
            asyncio.run(consume())
    else:
        assert len(asyncio.run(consume())) == 2
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith('{"bench"')]


def test_span_logs_start_and_end_with_usage():
    start, end = _bench_lines(fail=False)
    assert (start["checkpoint"], end["checkpoint"]) == ("llm_start", "llm_end")
    assert end["ok"] is True and end["error_type"] is None
    assert end["total_tokens"] == 5 and end["total_cost_usd"] == 0.001
    assert end["model"] == "gpt-4o-mini"


def test_span_logs_error_type_and_reraises():
    _, end = _bench_lines(fail=True)
    assert end["ok"] is False and end["error_type"] == "RuntimeError"


def test_span_counts_cancellation_as_failed():
    stream = io.StringIO()
    logger.remove()
    add_bench_sink(stream, "BENCH")

    async def slow_chunks():
        yield LLMChunk(delta_text="hi")
        await asyncio.sleep(10)

    async def main():
        first_chunk = asyncio.Event()

        async def consume():
            async for _ in _bench_llm_span(slow_chunks(), "gpt-4o-mini"):
                first_chunk.set()

        task = asyncio.create_task(consume())
        await first_chunk.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith('{"bench"')]
    end = lines[-1]
    assert end["checkpoint"] == "llm_end"
    assert end["ok"] is False and end["error_type"] == "CancelledError"
