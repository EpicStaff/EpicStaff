# hash per job: auditor:export_job:{job_id}
JOB_KEY_PREFIX = "auditor:export_job:"

# sorted set: member=job_id, score=expires_at
EXPIRY_ZSET_KEY = "auditor:export_jobs_by_expiry"

# set of job_ids owned by org_id and user_id pair
USER_KEY = "auditor:export_jobs_by_user:"


def user_jobs_key(org_id: int, user_id: int) -> str:
    return f"{USER_KEY}{org_id}:{user_id}"


def register_job(
    pipe,
    *,
    job_id: str,
    org_id: int,
    user_id: int,
    mapping: dict,
    hash_ttl_seconds: int,
    expires_at: float,
) -> None:
    job_key = f"{JOB_KEY_PREFIX}{job_id}"
    pipe.hset(job_key, mapping=mapping)
    pipe.expire(job_key, hash_ttl_seconds)
    pipe.zadd(EXPIRY_ZSET_KEY, {job_id: expires_at})

    index_key = user_jobs_key(org_id, user_id)
    pipe.sadd(index_key, job_id)
    pipe.expire(index_key, hash_ttl_seconds)


def deregister_job(pipe, *, job_id: str, org_id: int, user_id: int) -> None:
    pipe.delete(f"{JOB_KEY_PREFIX}{job_id}")
    pipe.zrem(EXPIRY_ZSET_KEY, job_id)
    pipe.srem(user_jobs_key(org_id, user_id), job_id)
