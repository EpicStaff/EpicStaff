from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from services.dashboard_build_service import DashboardBuildService
from services.redis_service import RedisService
from src.shared.redis_streams import DASHBOARD_BUILD_REQUESTED_AT_FIELD, DASHBOARD_BUILD_STREAM


@pytest_asyncio.fixture
async def redis_service():
    service = RedisService(host="unused", port=0)
    service.aioredis_client = FakeAsyncRedis(decode_responses=True)
    yield service
    await service.aioredis_client.aclose()


@pytest_asyncio.fixture
async def build_service(redis_service):
    service = DashboardBuildService(redis_service=redis_service, timezone=ZoneInfo("UTC"))
    yield service
    service.stop()


@pytest.mark.asyncio
async def test_job_fires_every_minute_without_overlap(build_service):
    await build_service.start()

    job = build_service.scheduler.get_job("dashboard_build")
    assert job.trigger.interval == timedelta(minutes=1)
    assert (job.coalesce, job.max_instances) == (True, 1)


@pytest.mark.asyncio
async def test_start_does_not_request_build_immediately(build_service, redis_service):
    await build_service.start()

    assert await redis_service.aioredis_client.xlen(DASHBOARD_BUILD_STREAM) == 0


@pytest.mark.asyncio
async def test_request_build_adds_one_entry_with_timestamp(build_service, redis_service):
    await build_service.request_build()

    entries = await redis_service.aioredis_client.xrange(DASHBOARD_BUILD_STREAM)
    assert len(entries) == 1
    assert DASHBOARD_BUILD_REQUESTED_AT_FIELD in entries[0][1]
