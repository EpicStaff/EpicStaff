import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from helpers.logger import logger
from services.redis_service import RedisService
from services.transfer_job_sweep_service import (
    TransferJobSweepService,
    request_transfer_job_sweep,
)
from src.shared.redis_streams import (
    TRANSFER_JOB_STREAM,
    TRANSFER_JOB_STREAM_MAXLEN,
    TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD,
)

TIMEZONE = ZoneInfo("Europe/Kyiv")


@pytest_asyncio.fixture
async def redis_service():
    service = RedisService(host="unused", port=0)
    service.aioredis_client = FakeAsyncRedis(decode_responses=True)
    yield service
    await service.aioredis_client.aclose()


@pytest_asyncio.fixture
async def sweep_service(redis_service):
    service = TransferJobSweepService(redis_service=redis_service, timezone=TIMEZONE)
    yield service
    service.stop()


# The request on its own, as any scheduler (APScheduler today, Celery beat later) calls it.


@pytest.mark.asyncio
async def test_request_adds_exactly_one_sweep_entry_with_timestamp(redis_service):
    await request_transfer_job_sweep(redis_service)

    entries = await redis_service.aioredis_client.xrange(TRANSFER_JOB_STREAM)
    assert len(entries) == 1
    fields = entries[0][1]
    assert set(fields) == {"sweep_requested_at"}
    requested_at = datetime.fromisoformat(fields[TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD])
    assert abs(datetime.now(UTC) - requested_at) < timedelta(minutes=1)


@pytest.mark.asyncio
async def test_repeated_requests_keep_the_stream_bounded(redis_service, monkeypatch):
    # A small cap keeps the test fast; approximate trimming still has to hold the stream near it.
    stream_cap = 100
    monkeypatch.setattr(
        "services.transfer_job_sweep_service.TRANSFER_JOB_STREAM_MAXLEN", stream_cap
    )
    for _ in range(stream_cap * 3):
        await request_transfer_job_sweep(redis_service)

    length = await redis_service.aioredis_client.xlen(TRANSFER_JOB_STREAM)
    assert length <= stream_cap * 2


@pytest.mark.asyncio
async def test_redis_error_propagates_so_the_caller_can_retry(redis_service, monkeypatch):
    async def failing_xadd(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(redis_service.aioredis_client, "xadd", failing_xadd)

    with pytest.raises(ConnectionError, match="redis is down"):
        await request_transfer_job_sweep(redis_service)


# The APScheduler wiring.


@pytest.mark.asyncio
async def test_job_fires_every_fifteen_minutes(sweep_service):
    await sweep_service.start()

    job = sweep_service.scheduler.get_job("transfer_job_sweep")
    first_fire = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    second_fire = job.trigger.get_next_fire_time(first_fire, first_fire + timedelta(seconds=1))
    assert second_fire - first_fire == timedelta(minutes=15)


@pytest.mark.asyncio
async def test_job_options_coalesce_and_never_overlap(sweep_service):
    await sweep_service.start()

    jobs = sweep_service.scheduler.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert (job.id, job.name) == ("transfer_job_sweep", "TransferJobSweep")
    assert (job.coalesce, job.max_instances) == (True, 1)
    assert job.misfire_grace_time > 0


@pytest.mark.asyncio
async def test_start_does_not_request_sweep_immediately(sweep_service, redis_service):
    await sweep_service.start()

    assert await redis_service.aioredis_client.xlen(TRANSFER_JOB_STREAM) == 0


@pytest.mark.asyncio
async def test_scheduled_job_requests_a_sweep_when_run(sweep_service, redis_service):
    await sweep_service.start()

    job = sweep_service.scheduler.get_job("transfer_job_sweep")
    await job.func(*job.args, **job.kwargs)

    entries = await redis_service.aioredis_client.xrange(TRANSFER_JOB_STREAM)
    assert len(entries) == 1
    assert TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD in entries[0][1]


@pytest.mark.asyncio
async def test_scheduled_job_logs_a_failing_request_and_does_not_raise(
    sweep_service, redis_service, monkeypatch
):
    async def failing_xadd(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(redis_service.aioredis_client, "xadd", failing_xadd)
    await sweep_service.start()
    job = sweep_service.scheduler.get_job("transfer_job_sweep")

    messages = []
    sink_id = logger.add(messages.append, level="ERROR")
    try:
        await job.func(*job.args, **job.kwargs)
    finally:
        logger.remove(sink_id)

    assert any("redis is down" in str(message) for message in messages)


@pytest.mark.asyncio
async def test_stop_shuts_the_scheduler_down(sweep_service):
    await sweep_service.start()

    sweep_service.stop()
    # AsyncIOScheduler runs shutdown on the event loop, so let the loop take one turn.
    await asyncio.sleep(0)

    assert not sweep_service.scheduler.running
