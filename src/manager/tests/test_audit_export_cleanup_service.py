import asyncio
import time
import uuid

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from services.audit_export_cleanup_service import ExportCleanupService
from src.shared.audit.export_jobs import EXPIRY_ZSET_KEY, JOB_KEY_PREFIX, user_jobs_key


@pytest_asyncio.fixture
async def redis_client():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def export_dir(tmp_path):
    directory = tmp_path / "export_data"
    directory.mkdir()
    yield directory


@pytest.fixture
def cleanup_service(redis_client, export_dir):
    return ExportCleanupService(redis_client=redis_client, export_data_dir=str(export_dir))


async def _seed_job(
    redis_client, job_id: str, *, expires_at: float, file_path: str = ""
):
    key = f"{JOB_KEY_PREFIX}{job_id}"
    await redis_client.hset(
        key,
        mapping={
            "status": "completed",
            "domain": "sessions",
            "org_id": 1,
            "user_id": 1,
            "file_path": file_path,
        },
    )
    await redis_client.zadd(EXPIRY_ZSET_KEY, {job_id: expires_at})


@pytest.mark.asyncio
async def test_sweep_once_deletes_expired_job_and_its_file(
    redis_client, cleanup_service, export_dir
):
    export_file = export_dir / "job-1.json"
    export_file.write_text("[]")
    await _seed_job(
        redis_client, "job-1", expires_at=time.time() - 10, file_path=str(export_file)
    )
    # _seed_job writes org_id=1, user_id=1, so the per-user index lives under that pair.
    index_key = user_jobs_key("sessions", 1, 1)
    await redis_client.sadd(index_key, "job-1")

    await cleanup_service.sweep_once()

    assert not export_file.exists()
    assert await redis_client.hgetall(f"{JOB_KEY_PREFIX}job-1") == {}
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "job-1") is None
    assert not await redis_client.sismember(index_key, "job-1")


@pytest.mark.asyncio
async def test_sweep_once_leaves_unexpired_job_untouched(
    redis_client, cleanup_service, export_dir
):
    export_file = export_dir / "job-2.json"
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
    redis_client, cleanup_service, export_dir
):
    # The hash's native TTL backstop fired before this sweep ran (manager was
    # down a while) - file_path is unrecoverable from Redis, but the file is
    # still deterministically named "{job_id}.<ext>" under export_data_dir,
    # so the sweep must still find and delete it rather than leaking it.
    job_id = str(uuid.uuid4())
    export_file = export_dir / f"{job_id}.json"
    export_file.write_text("[]")
    await redis_client.zadd(EXPIRY_ZSET_KEY, {job_id: time.time() - 10})

    await cleanup_service.sweep_once()

    assert not export_file.exists()
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, job_id) is None


@pytest.mark.asyncio
async def test_sweep_once_refuses_to_delete_file_path_outside_export_dir(
    redis_client, cleanup_service, tmp_path
):
    outside_file = tmp_path / "not-an-export.txt"
    outside_file.write_text("keep me")
    traversal_path = f"{cleanup_service.export_data_dir}/../not-an-export.txt"
    await _seed_job(
        redis_client, "job-evil", expires_at=time.time() - 10, file_path=traversal_path
    )

    await cleanup_service.sweep_once()

    assert outside_file.exists()
    # the job record is still deregistered so the sweep does not retry it forever
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "job-evil") is None


@pytest.mark.asyncio
async def test_sweep_once_refuses_symlink_escaping_export_dir(
    redis_client, cleanup_service, export_dir, tmp_path
):
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("keep me")
    link = export_dir / "job-link.json"
    try:
        link.symlink_to(outside_file)
    except OSError:
        pytest.skip("symlinks not permitted on this platform")
    await _seed_job(
        redis_client, "job-link", expires_at=time.time() - 10, file_path=str(link)
    )

    await cleanup_service.sweep_once()

    assert outside_file.exists()


@pytest.mark.asyncio
async def test_sweep_once_with_wildcard_job_id_deletes_no_files(
    redis_client, cleanup_service, export_dir
):
    other_exports = [export_dir / f"{uuid.uuid4()}.json" for _ in range(3)]
    for export_file in other_exports:
        export_file.write_text("[]")
    await redis_client.zadd(EXPIRY_ZSET_KEY, {"*": time.time() - 10})

    await cleanup_service.sweep_once()

    assert all(export_file.exists() for export_file in other_exports)
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "*") is None


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
async def test_sweep_once_still_cleans_other_jobs_when_one_job_fails(
    redis_client, cleanup_service, export_dir
):
    # Unlinking a directory raises, so this job's cleanup fails mid-way.
    undeletable_path = export_dir / "job-broken.json"
    undeletable_path.mkdir()
    await _seed_job(
        redis_client, "job-broken", expires_at=time.time() - 10, file_path=str(undeletable_path)
    )
    export_file = export_dir / "job-ok.json"
    export_file.write_text("[]")
    await _seed_job(
        redis_client, "job-ok", expires_at=time.time() - 10, file_path=str(export_file)
    )

    await cleanup_service.sweep_once()

    assert not export_file.exists()
    assert await redis_client.zscore(EXPIRY_ZSET_KEY, "job-ok") is None


@pytest.mark.asyncio
async def test_started_service_sweeps_until_stopped(redis_client, export_dir):
    service = ExportCleanupService(
        redis_client=redis_client, export_data_dir=str(export_dir), sweep_interval_seconds=0.01
    )
    await service.start()
    try:
        export_file = export_dir / "job-live.json"
        export_file.write_text("[]")
        await _seed_job(
            redis_client, "job-live", expires_at=time.time() - 10, file_path=str(export_file)
        )
        deadline = asyncio.get_running_loop().time() + 2
        while export_file.exists() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert not export_file.exists()
    finally:
        await service.stop()

    later_file = export_dir / "job-after-stop.json"
    later_file.write_text("[]")
    await _seed_job(
        redis_client, "job-after-stop", expires_at=time.time() - 10, file_path=str(later_file)
    )
    await asyncio.sleep(0.05)
    assert later_file.exists()
