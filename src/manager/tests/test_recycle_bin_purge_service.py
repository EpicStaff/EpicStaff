from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from helpers.logger import logger
from services.recycle_bin_purge_service import RecycleBinPurgeService
from services.redis_service import RedisService
from src.shared.redis_streams import (
    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD,
    RECYCLE_BIN_PURGE_STREAM,
    RECYCLE_BIN_PURGE_STREAM_MAXLEN,
)

TIMEZONE = ZoneInfo("Europe/Kyiv")


@pytest_asyncio.fixture
async def redis_service():
    service = RedisService(host="unused", port=0)
    service.aioredis_client = FakeAsyncRedis(decode_responses=True)
    yield service
    await service.aioredis_client.aclose()


@pytest_asyncio.fixture
async def purge_service(redis_service):
    service = RecycleBinPurgeService(redis_service=redis_service, timezone=TIMEZONE)
    yield service
    service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("now_local", "expected_fire_utc"),
    [
        # Winter (UTC+2): 03:00 local is 01:00 UTC.
        (datetime(2026, 1, 10, 12, 0, tzinfo=TIMEZONE), datetime(2026, 1, 11, 1, 0, tzinfo=UTC)),
        # Summer (UTC+3): 03:00 local is 00:00 UTC.
        (datetime(2026, 7, 10, 12, 0, tzinfo=TIMEZONE), datetime(2026, 7, 11, 0, 0, tzinfo=UTC)),
        # Spring-forward day (2026-03-29): fires once, at the same instant 03:00 winter time was.
        (datetime(2026, 3, 28, 12, 0, tzinfo=TIMEZONE), datetime(2026, 3, 29, 1, 0, tzinfo=UTC)),
        # The day after it runs on summer time.
        (datetime(2026, 3, 29, 12, 0, tzinfo=TIMEZONE), datetime(2026, 3, 30, 0, 0, tzinfo=UTC)),
        # Fall-back day (2026-10-25): 03:00 summer time, once.
        (datetime(2026, 10, 24, 12, 0, tzinfo=TIMEZONE), datetime(2026, 10, 25, 0, 0, tzinfo=UTC)),
        (datetime(2026, 10, 25, 12, 0, tzinfo=TIMEZONE), datetime(2026, 10, 26, 1, 0, tzinfo=UTC)),
    ],
)
async def test_the_job_fires_daily_at_three_am_local_time(
    purge_service, now_local, expected_fire_utc
):
    await purge_service.start()

    job = purge_service.scheduler.get_job("recycle_bin_purge")

    # Compared in UTC: == on a local time inside a DST gap or fold is always False.
    fire_time = job.trigger.get_next_fire_time(None, now_local)
    assert fire_time.astimezone(UTC) == expected_fire_utc


@pytest.mark.asyncio
async def test_missed_fires_are_coalesced_and_never_overlap(purge_service):
    await purge_service.start()

    job = purge_service.scheduler.get_job("recycle_bin_purge")
    assert (job.coalesce, job.max_instances) == (True, 1)


@pytest.mark.asyncio
async def test_start_does_not_request_purge_immediately(purge_service, redis_service):
    await purge_service.start()

    assert await redis_service.aioredis_client.xlen(RECYCLE_BIN_PURGE_STREAM) == 0


@pytest.mark.asyncio
async def test_firing_adds_exactly_one_entry_with_timestamp(purge_service, redis_service):
    await purge_service.request_purge()

    entries = await redis_service.aioredis_client.xrange(RECYCLE_BIN_PURGE_STREAM)
    assert len(entries) == 1
    requested_at = entries[0][1][RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD]
    assert datetime.fromisoformat(requested_at).tzinfo is not None


@pytest.mark.asyncio
async def test_stream_length_stays_bounded(purge_service, redis_service):
    for _ in range(RECYCLE_BIN_PURGE_STREAM_MAXLEN * 3):
        await purge_service.request_purge()

    length = await redis_service.aioredis_client.xlen(RECYCLE_BIN_PURGE_STREAM)
    assert length <= RECYCLE_BIN_PURGE_STREAM_MAXLEN * 2


@pytest.mark.asyncio
async def test_redis_error_on_fire_is_logged_not_raised(purge_service, redis_service, monkeypatch):
    async def failing_xadd(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(redis_service.aioredis_client, "xadd", failing_xadd)
    messages = []
    sink_id = logger.add(messages.append, level="ERROR")
    try:
        await purge_service.request_purge()
    finally:
        logger.remove(sink_id)

    assert any("redis is down" in str(message) for message in messages)
