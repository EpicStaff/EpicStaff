import time

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from services.audit_export_cleanup_service import ExportCleanupService
from src.shared.audit.export_jobs import EXPIRY_ZSET_KEY, JOB_KEY_PREFIX


@pytest_asyncio.fixture
async def redis_client():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def cleanup_service(redis_client):
    return ExportCleanupService(redis_client=redis_client)


async def _seed_job(redis_client, job_id: str, *, expires_at: float, file_path: str = ""):
    key = f"{JOB_KEY_PREFIX}{job_id}"
    await redis_client.hset(
        key,
        mapping={"status": "completed", "org_id": 1, "user_id": 1, "file_path": file_path},
    )
    await redis_client.zadd(EXPIRY_ZSET_KEY, {job_id: expires_at})


@pytest.mark.asyncio
async def test_sweep_once_deletes_expired_job_and_its_file(
    redis_client, cleanup_service, tmp_path
):
    export_file = tmp_path / "job-1.json"
    export_file.write_text("[]")
    await _seed_job(
        redis_client, "job-1", expires_at=time.time() - 10, file_path=str(export_file)
    )

    await cleanup_service.sweep_once()

    assert not export_file.exists()
    assert await redis_client.hgetall(f"{JOB_KEY_PREFIX}job-1") == {}
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "job-1") is None


@pytest.mark.asyncio
async def test_sweep_once_leaves_unexpired_job_untouched(
    redis_client, cleanup_service, tmp_path
):
    export_file = tmp_path / "job-2.json"
    export_file.write_text("[]")
    await _seed_job(
        redis_client, "job-2", expires_at=time.time() + 3600, file_path=str(export_file)
    )

    await cleanup_service.sweep_once()

    assert export_file.exists()
    assert await redis_client.hgetall(f"{JOB_KEY_PREFIX}job-2") != {}
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "job-2") is not None


@pytest.mark.asyncio
async def test_sweep_once_falls_back_to_glob_when_hash_already_gone(
    redis_client, tmp_path
):
    # The hash's native TTL backstop fired before this sweep ran (manager was
    # down a while) - file_path is unrecoverable from Redis, but the file is
    # still deterministically named "{job_id}.<ext>" under export_data_dir,
    # so the sweep must still find and delete it rather than leaking it.
    service = ExportCleanupService(
        redis_client=redis_client, export_data_dir=str(tmp_path)
    )
    export_file = tmp_path / "orphaned-job.json"
    export_file.write_text("[]")
    await redis_client.zadd(EXPIRY_ZSET_KEY, {"orphaned-job": time.time() - 10})

    await service.sweep_once()

    assert not export_file.exists()
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "orphaned-job") is None


@pytest.mark.asyncio
async def test_sweep_once_tolerates_hash_already_gone(redis_client, cleanup_service):
    # Simulates the native TTL backstop firing before the sweep runs: the
    # zset entry survives (zadd carries no TTL of its own) but the hash is
    # already gone. Sweeping it must not raise - just clean up the zset.
    await redis_client.zadd(EXPIRY_ZSET_KEY, {"orphaned-job": time.time() - 10})

    await cleanup_service.sweep_once()

    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "orphaned-job") is None


@pytest.mark.asyncio
async def test_sweep_once_with_no_file_path_only_cleans_redis(
    redis_client, cleanup_service
):
    # A job that never reached "completed" (still pending/failed) has an
    # empty file_path - nothing to unlink, but the job record should still
    # be swept once past its TTL.
    await _seed_job(redis_client, "job-3", expires_at=time.time() - 10, file_path="")

    await cleanup_service.sweep_once()

    assert await redis_client.hgetall(f"{JOB_KEY_PREFIX}job-3") == {}
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "job-3") is None


@pytest.mark.asyncio
async def test_sweep_once_handles_multiple_due_jobs(redis_client, cleanup_service, tmp_path):
    for i in range(3):
        f = tmp_path / f"job-{i}.json"
        f.write_text("[]")
        await _seed_job(redis_client, f"job-{i}", expires_at=time.time() - 1, file_path=str(f))

    await cleanup_service.sweep_once()

    for i in range(3):
        assert not (tmp_path / f"job-{i}.json").exists()
        assert await redis_client.zscore(EXPIRY_ZSET_KEY, f"job-{i}") is None


@pytest.mark.asyncio
async def test_start_and_stop_run_sweep_loop_without_error(redis_client):
    service = ExportCleanupService(redis_client=redis_client, sweep_interval_seconds=60)
    await service.start()
    assert service._task is not None
    await service.stop()
    assert service._task is None
