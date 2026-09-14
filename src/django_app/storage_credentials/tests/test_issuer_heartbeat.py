import asyncio
import os
import subprocess
import sys
import time

import pytest
from fakeredis.aioredis import FakeRedis
from loguru import logger

from storage_credentials.heartbeat_constants import ISSUER_HEARTBEAT_KEY_TTL_SECONDS
from storage_credentials.redis.heartbeat import IssuerHeartbeat
from storage_credentials.redis.keys import ISSUER_HEARTBEAT_KEY

HEALTHCHECK_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "healthcheck.py"
)


async def _wait_until(predicate, timeout=2.0, interval=0.01):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met before timeout")


async def _cancel_and_await(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class _FailingRedisClient:
    def __init__(self):
        self.set_call_count = 0

    async def set(self, *args, **kwargs):
        self.set_call_count += 1
        raise RuntimeError("redis unreachable")


def _run_healthcheck(env_overrides):
    env = {**os.environ, **env_overrides}
    result = subprocess.run(
        [sys.executable, HEALTHCHECK_SCRIPT], env=env, capture_output=True
    )
    return result.returncode


@pytest.mark.asyncio
async def test_run_forever_writes_redis_key_and_touches_file(tmp_path):
    redis_client = FakeRedis()
    heartbeat_file_path = str(tmp_path / "heartbeat")
    heartbeat = IssuerHeartbeat(
        redis_client=redis_client, heartbeat_file_path=heartbeat_file_path
    )

    task = asyncio.create_task(heartbeat.run_forever())
    try:
        await asyncio.wait_for(
            _wait_until(lambda: os.path.exists(heartbeat_file_path)), timeout=2.0
        )
    finally:
        await _cancel_and_await(task)

    assert os.path.exists(heartbeat_file_path)
    ttl = await redis_client.ttl(ISSUER_HEARTBEAT_KEY)
    assert 0 < ttl <= ISSUER_HEARTBEAT_KEY_TTL_SECONDS
    assert await redis_client.get(ISSUER_HEARTBEAT_KEY) == b"1"

    await redis_client.aclose()


@pytest.mark.asyncio
async def test_run_forever_survives_redis_failure_without_touching_file(tmp_path):
    redis_client = _FailingRedisClient()
    heartbeat_file_path = str(tmp_path / "heartbeat")
    heartbeat = IssuerHeartbeat(
        redis_client=redis_client, heartbeat_file_path=heartbeat_file_path
    )

    logged_messages = []
    sink_id = logger.add(lambda message: logged_messages.append(message), level="ERROR")

    task = asyncio.create_task(heartbeat.run_forever())
    try:
        await asyncio.wait_for(
            _wait_until(lambda: redis_client.set_call_count >= 1), timeout=2.0
        )
        await asyncio.sleep(0.05)
        assert not task.done()
    finally:
        logger.remove(sink_id)
        await _cancel_and_await(task)

    assert not os.path.exists(heartbeat_file_path)
    assert any(
        "failed to write heartbeat" in str(message) for message in logged_messages
    )


@pytest.mark.asyncio
async def test_run_forever_propagates_cancelled_error_without_being_swallowed(tmp_path):
    redis_client = FakeRedis()
    heartbeat = IssuerHeartbeat(
        redis_client=redis_client, heartbeat_file_path=str(tmp_path / "heartbeat")
    )

    task = asyncio.create_task(heartbeat.run_forever())
    await asyncio.sleep(0.05)
    await _cancel_and_await(task)

    assert task.cancelled()

    await redis_client.aclose()


def test_healthcheck_returns_zero_for_fresh_file(tmp_path):
    heartbeat_file = tmp_path / "heartbeat"
    heartbeat_file.touch()

    returncode = _run_healthcheck(
        {"HEARTBEAT_FILE": str(heartbeat_file), "HEARTBEAT_MAX_AGE_SECONDS": "20"}
    )

    assert returncode == 0


def test_healthcheck_returns_one_for_stale_file(tmp_path):
    heartbeat_file = tmp_path / "heartbeat"
    heartbeat_file.touch()
    stale_time = time.time() - 100
    os.utime(heartbeat_file, (stale_time, stale_time))

    returncode = _run_healthcheck(
        {"HEARTBEAT_FILE": str(heartbeat_file), "HEARTBEAT_MAX_AGE_SECONDS": "20"}
    )

    assert returncode == 1


def test_healthcheck_returns_one_for_missing_file(tmp_path):
    heartbeat_file = tmp_path / "missing_heartbeat"

    returncode = _run_healthcheck(
        {"HEARTBEAT_FILE": str(heartbeat_file), "HEARTBEAT_MAX_AGE_SECONDS": "20"}
    )

    assert returncode == 1
