"""
Tests for SandboxClient.

Mocks redis.asyncio so no real Redis is needed.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.sandbox.client import SandboxClient
from shared.models.tools import CodeResultData, CodeTaskData


def _make_client() -> SandboxClient:
    return SandboxClient(
        host="127.0.0.1",
        port=6379,
        password=None,
        request_channel="code_exec_tasks",
        result_channel="code_results",
    )


def _make_task(execution_id: str = "placeholder") -> CodeTaskData:
    return CodeTaskData(
        venv_name="venv_test",
        libraries=[],
        code="def main(): return 'ok'",
        execution_id=execution_id,
        entrypoint="main",
        func_kwargs={},
        global_kwargs={},
    )


def _result_message(execution_id: str, result_data: str = "ok") -> dict:
    payload = CodeResultData(
        execution_id=execution_id,
        result_data=result_data,
        stderr="",
        stdout="",
        returncode=0,
    )
    return {"type": "message", "data": payload.model_dump_json().encode()}


async def _make_async_generator(items):
    for item in items:
        yield item


@pytest.fixture
def mock_redis_factory():
    """Returns a factory that builds a pre-configured mock Redis + pubsub pair."""

    def factory(messages: list[dict] | None = None):
        messages = messages or []
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.close = AsyncMock()
        pubsub.listen = MagicMock(return_value=_make_async_generator(messages))

        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock()
        redis_mock.aclose = AsyncMock()
        redis_mock.pubsub = MagicMock(return_value=pubsub)

        return redis_mock, pubsub

    return factory


async def test_start_subscribes_to_result_channel(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory()

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        pubsub.subscribe.assert_called_once_with("code_results")

    await client.stop()


async def test_start_is_idempotent(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory()

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()
        await client.start()

        pubsub.subscribe.assert_called_once()

    await client.stop()


async def test_submit_publishes_to_request_channel(mock_redis_factory):
    execution_id = "test-exec-1"
    result_msg = _result_message(execution_id)
    redis_mock, pubsub = mock_redis_factory(
        messages=[
            {"type": "subscribe", "data": 1},
            result_msg,
        ]
    )

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        task = _make_task()
        with patch("app.sandbox.client.uuid.uuid4", return_value=execution_id):
            result = await asyncio.wait_for(client.submit(task), timeout=2.0)

        redis_mock.publish.assert_called_once()
        call_args = redis_mock.publish.call_args
        assert call_args[0][0] == "code_exec_tasks"
        published_data = json.loads(call_args[0][1])
        assert published_data["execution_id"] == execution_id

        assert result.execution_id == execution_id
        assert result.result_data == "ok"

    await client.stop()


async def test_reader_loop_resolves_pending_future(mock_redis_factory):
    execution_id = "exec-resolve"
    result_msg = _result_message(execution_id, result_data="hello")
    redis_mock, pubsub = mock_redis_factory(messages=[result_msg])

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        task = _make_task()
        with patch("app.sandbox.client.uuid.uuid4", return_value=execution_id):
            result = await asyncio.wait_for(client.submit(task), timeout=2.0)

        assert result.result_data == "hello"
        assert result.returncode == 0

    await client.stop()


async def test_two_concurrent_submits_demuxed_by_execution_id():
    # Build a client where we intercept publish to capture execution IDs,
    # then feed matching results back via the pubsub listener.
    captured_ids: list[str] = []
    id_queue: asyncio.Queue[str] = asyncio.Queue()

    async def capture_publish(channel, payload):
        import json as _json

        data = _json.loads(payload)
        eid = data["execution_id"]
        captured_ids.append(eid)
        await id_queue.put(eid)

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.close = AsyncMock()

    async def dynamic_listener():
        delivered = 0
        while delivered < 2:
            eid = await id_queue.get()
            result = CodeResultData(
                execution_id=eid,
                result_data=f"result-for-{eid}",
                stderr="",
                stdout="",
                returncode=0,
            )
            yield {"type": "message", "data": result.model_dump_json().encode()}
            delivered += 1

    pubsub.listen = MagicMock(return_value=dynamic_listener())

    redis_mock = MagicMock()
    redis_mock.publish = AsyncMock(side_effect=capture_publish)
    redis_mock.aclose = AsyncMock()
    redis_mock.pubsub = MagicMock(return_value=pubsub)

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        result_1, result_2 = await asyncio.wait_for(
            asyncio.gather(client.submit(_make_task()), client.submit(_make_task())),
            timeout=2.0,
        )

    assert len(captured_ids) == 2
    assert captured_ids[0] != captured_ids[1]
    assert result_1.result_data == f"result-for-{result_1.execution_id}"
    assert result_2.result_data == f"result-for-{result_2.execution_id}"

    await client.stop()


async def test_cancellation_removes_future(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory(messages=[])

    async def never_ending():
        while True:
            yield {"type": "subscribe", "data": 1}
            await asyncio.sleep(10)

    pubsub.listen = MagicMock(return_value=never_ending())

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        task_coro = asyncio.create_task(client.submit(_make_task()))
        await asyncio.sleep(0.01)
        task_coro.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task_coro

        assert len(client._pending) == 0

    await client.stop()


async def test_stop_fails_pending_futures(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory(messages=[])

    async def never_ending():
        while True:
            yield {"type": "subscribe", "data": 1}
            await asyncio.sleep(10)

    pubsub.listen = MagicMock(return_value=never_ending())

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        submit_task = asyncio.create_task(client.submit(_make_task()))
        await asyncio.sleep(0.01)
        await client.stop()

        with pytest.raises(ConnectionError, match="SandboxClient stopped"):
            await submit_task


async def test_malformed_message_is_skipped(mock_redis_factory):
    execution_id = "exec-after-malformed"
    valid_msg = _result_message(execution_id, result_data="survived")
    malformed_msg = {"type": "message", "data": b"not valid json {{{"}
    redis_mock, pubsub = mock_redis_factory(messages=[malformed_msg, valid_msg])

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()

        task = _make_task()
        with patch("app.sandbox.client.uuid.uuid4", return_value=execution_id):
            result = await asyncio.wait_for(client.submit(task), timeout=2.0)

        assert result.result_data == "survived"

    await client.stop()


async def test_stop_closes_redis_and_pubsub(mock_redis_factory):
    redis_mock, pubsub = mock_redis_factory()

    with patch("app.sandbox.client.aioredis.Redis", return_value=redis_mock):
        client = _make_client()
        await client.start()
        await client.stop()

        pubsub.close.assert_called_once()
        redis_mock.aclose.assert_called_once()
