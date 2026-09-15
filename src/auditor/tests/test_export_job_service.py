import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis

from app.services.export_job_service import ExportJobService, JobStatus


@pytest_asyncio.fixture
async def job_service():
    redis_client = FakeAsyncRedis(decode_responses=True)
    yield ExportJobService(redis_client)
    await redis_client.aclose()


@pytest.mark.asyncio
async def test_create_job_writes_hash_fields(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=7, user_id=42, ttl_seconds=3600, format="csv"
    )
    job = await job_service.get_job("job-1")

    assert job["status"] == JobStatus.PENDING.value
    assert job["org_id"] == "7"
    assert job["user_id"] == "42"
    assert job["format"] == "csv"
    assert job["file_path"] == ""


@pytest.mark.asyncio
async def test_create_job_registers_expiry_in_sorted_set(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    score = await job_service._redis.zscore(
        "auditor:export_jobs_by_expiry", "job-1"
    )
    assert score is not None
    assert score > 0


@pytest.mark.asyncio
async def test_create_job_sets_native_ttl_backstop(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    ttl = await job_service._redis.ttl("auditor:export_job:job-1")
    assert ttl > 0


@pytest.mark.asyncio
async def test_mark_done_sets_status_and_file_path(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    was_recorded = await job_service.mark_done("job-1", "/app/export_data/job-1.json")

    assert was_recorded is True
    job = await job_service.get_job("job-1")
    assert job["status"] == JobStatus.COMPLETED.value
    assert job["file_path"] == "/app/export_data/job-1.json"


@pytest.mark.asyncio
async def test_mark_failed_sets_status_and_error(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    was_recorded = await job_service.mark_failed("job-1", "boom")

    assert was_recorded is True
    job = await job_service.get_job("job-1")
    assert job["status"] == JobStatus.FAILED.value
    assert job["error"] == "boom"


@pytest.mark.asyncio
async def test_mark_done_returns_false_for_deleted_job(job_service):
    # Simulates a manual delete (or the manager's sweep) racing ahead of a
    # still-running export - must not resurrect the hash with no TTL and no
    # zset entry, which would leak it forever.
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    await job_service.delete_job("job-1", 1, 1)

    was_recorded = await job_service.mark_done("job-1", "/app/export_data/job-1.json")

    assert was_recorded is False
    assert await job_service.get_job("job-1") is None


@pytest.mark.asyncio
async def test_mark_failed_returns_false_for_deleted_job(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    await job_service.delete_job("job-1", 1, 1)

    was_recorded = await job_service.mark_failed("job-1", "boom")

    assert was_recorded is False
    assert await job_service.get_job("job-1") is None


@pytest.mark.asyncio
async def test_create_job_hash_ttl_outlives_the_expiry_ttl(job_service):
    # The hash's own native TTL is a failsafe for when the manager sweep is
    # down - it must always outlive ttl_seconds by a safety margin, or the
    # hash (and the job's downloadability) vanishes before the job's own
    # intended expiry.
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    hash_ttl = await job_service._redis.ttl("auditor:export_job:job-1")
    assert hash_ttl > 3600


@pytest.mark.asyncio
async def test_get_job_returns_none_for_unknown_id(job_service):
    assert await job_service.get_job("does-not-exist") is None


@pytest.mark.asyncio
async def test_delete_job_removes_hash_and_zset_entry(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    await job_service.delete_job("job-1", 1, 1)

    assert await job_service.get_job("job-1") is None
    score = await job_service._redis.zscore(
        "auditor:export_jobs_by_expiry", "job-1"
    )
    assert score is None


@pytest.mark.asyncio
async def test_delete_job_is_idempotent_for_unknown_id(job_service):
    # Should not raise even though nothing was ever created for this id -
    # the manual-delete endpoint relies on this being a safe no-op path
    # after ownership has already been checked separately.
    await job_service.delete_job("never-existed", 1, 1)


@pytest.mark.asyncio
async def test_get_jobs_returns_hydrated_dicts_for_job_ids(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    await job_service.create_job(
        job_id="job-2", org_id=1, user_id=1, ttl_seconds=3600, format="csv"
    )

    jobs = await job_service.get_jobs(["job-1", "job-2"])

    assert {j["job_id"] for j in jobs} == {"job-1", "job-2"}
    for job in jobs:
        assert "job_id" in job
        assert "status" in job


@pytest.mark.asyncio
async def test_get_jobs_skips_ids_whose_hash_has_vanished(job_service):
    await job_service.create_job(
        job_id="job-1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    # "job-missing" was never created (simulates an expired/swept hash).
    jobs = await job_service.get_jobs(["job-1", "job-missing"])

    assert [j["job_id"] for j in jobs] == ["job-1"]


@pytest.mark.asyncio
async def test_get_jobs_returns_empty_list_for_empty_input(job_service):
    assert await job_service.get_jobs([]) == []


@pytest.mark.asyncio
async def test_get_jobs_by_user_returns_only_that_users_jobs(job_service):
    await job_service.create_job(
        job_id="job-a1", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    await job_service.create_job(
        job_id="job-a2", org_id=1, user_id=1, ttl_seconds=3600, format="json"
    )
    await job_service.create_job(
        job_id="job-b1", org_id=2, user_id=2, ttl_seconds=3600, format="json"
    )

    jobs = await job_service.get_jobs_by_user(org_id=1, user_id=1)

    assert {j["job_id"] for j in jobs} == {"job-a1", "job-a2"}


@pytest.mark.asyncio
async def test_get_jobs_by_user_returns_empty_list_when_no_jobs(job_service):
    assert await job_service.get_jobs_by_user(org_id=1, user_id=1) == []
