"""ExportJobService against fake Redis.

The job hash, the expiry sorted set and the per-user index are a contract with the
manager's cleanup sweep (src/shared/audit/export_jobs.py), so they are asserted directly.
"""

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis, FakeServer

from app.services.export_job_service import ExportJobService, JobStatus
from src.shared.audit.export_jobs import EXPIRY_ZSET_KEY, JOB_KEY_PREFIX

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def job_service():
    redis_client = FakeAsyncRedis(decode_responses=True)
    yield ExportJobService(redis_client)
    await redis_client.aclose()


async def _create(job_service, job_id="job-1", *, domain="sessions", org_id=1, user_id=1):
    await job_service.create_job(
        domain=domain, job_id=job_id, org_id=org_id, user_id=user_id,
        ttl_seconds=3600, format="csv",
    )


async def test_created_job_is_registered_for_the_managers_sweep(job_service):
    await _create(job_service, org_id=7, user_id=42)

    job = await job_service.get_job("job-1")
    assert (job["status"], job["domain"], job["org_id"], job["user_id"], job["format"]) == (
        JobStatus.PENDING.value, "sessions", "7", "42", "csv",
    )
    redis = job_service._redis
    assert await redis.zscore(EXPIRY_ZSET_KEY, "job-1") == pytest.approx(float(job["expires_at"]))
    # The hash's own TTL is the backstop when the sweep is down: it must outlive the job.
    assert await redis.ttl(f"{JOB_KEY_PREFIX}job-1") > 3600


@pytest.mark.parametrize("truncated", [False, True])
async def test_mark_done_records_the_file_and_truncation(job_service, truncated):
    await _create(job_service)

    assert await job_service.mark_done("job-1", "/exports/job-1.json", truncated=truncated)

    job = await job_service.get_job("job-1")
    assert (job["status"], job["file_path"], job["truncated"]) == (
        JobStatus.COMPLETED.value, "/exports/job-1.json", str(truncated),
    )


async def test_mark_failed_records_only_the_status(job_service):
    await _create(job_service)

    assert await job_service.mark_failed("job-1")

    job = await job_service.get_job("job-1")
    assert job["status"] == JobStatus.FAILED.value
    assert "error" not in job


def _mark_done(service):
    return service.mark_done("job-1", "/exports/job-1.json", truncated=False)


def _mark_failed(service):
    return service.mark_failed("job-1")


@pytest.mark.parametrize("finish", [_mark_done, _mark_failed], ids=["done", "failed"])
async def test_finishing_a_deleted_job_does_not_resurrect_it(job_service, finish):
    """A delete (manual or the sweep) racing ahead of a running export must not
    recreate the hash with no TTL and no expiry entry, which would leak it forever."""
    await _create(job_service)
    await job_service.delete_job("job-1", 1, 1, "sessions")

    assert await finish(job_service) is False
    assert await job_service.get_job("job-1") is None


async def _job_service_with_delete_racing_the_write():
    """Deletes the job hash from a second connection right after the existence check
    inside the update transaction - the window a check-then-write would lose."""
    server = FakeServer()
    redis_client = FakeAsyncRedis(server=server, decode_responses=True)
    racing_client = FakeAsyncRedis(server=server, decode_responses=True)
    service = ExportJobService(redis_client)
    await _create(service)

    open_pipeline = redis_client.pipeline
    race_state = {"deleted": False}

    def pipeline_with_racing_delete(*args, **kwargs):
        pipe = open_pipeline(*args, **kwargs)
        check_exists = pipe.exists

        async def exists_then_delete(*keys):
            result = await check_exists(*keys)
            if not race_state["deleted"]:
                race_state["deleted"] = True
                await racing_client.delete(f"{JOB_KEY_PREFIX}job-1")
            return result

        pipe.exists = exists_then_delete
        return pipe

    redis_client.pipeline = pipeline_with_racing_delete
    return service, redis_client, racing_client


@pytest.mark.parametrize("finish", [_mark_done, _mark_failed], ids=["done", "failed"])
async def test_finishing_does_not_resurrect_a_job_deleted_mid_update(finish):
    service, redis_client, racing_client = await _job_service_with_delete_racing_the_write()

    assert await finish(service) is False
    assert await racing_client.exists(f"{JOB_KEY_PREFIX}job-1") == 0
    await redis_client.aclose()
    await racing_client.aclose()


async def test_delete_removes_the_job_and_its_expiry_entry(job_service):
    await _create(job_service)

    await job_service.delete_job("job-1", 1, 1, "sessions")

    assert await job_service.get_job("job-1") is None
    assert await job_service._redis.zscore(EXPIRY_ZSET_KEY, "job-1") is None


async def test_user_listing_is_scoped_to_domain_org_and_user_and_skips_expired_jobs(job_service):
    await _create(job_service, "job-mine-1")
    await _create(job_service, "job-mine-2")
    await _create(job_service, "job-expired")
    await _create(job_service, "job-other-user", org_id=2, user_id=2)
    await _create(job_service, "job-other-domain", domain="billing")
    # The hash's native TTL fired, but the index entry is still there.
    await job_service._redis.delete(f"{JOB_KEY_PREFIX}job-expired")

    jobs = await job_service.get_jobs_by_user("sessions", org_id=1, user_id=1)

    assert {job["job_id"] for job in jobs} == {"job-mine-1", "job-mine-2"}


async def test_delete_only_touches_its_own_domains_index(job_service):
    await _create(job_service, "job-1", domain="sessions")
    await _create(job_service, "job-2", domain="billing")

    await job_service.delete_job("job-1", 1, 1, "sessions")

    billing_jobs = await job_service.get_jobs_by_user("billing", org_id=1, user_id=1)
    assert {job["job_id"] for job in billing_jobs} == {"job-2"}
