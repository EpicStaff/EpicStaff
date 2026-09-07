JOB_KEY_PREFIX = "auditor:export_job:"  # hash per job: auditor:export_job:{job_id}
EXPIRY_ZSET_KEY = (
    "auditor:export_jobs_by_expiry"  # sorted set: member=job_id, score=expires_at
)
