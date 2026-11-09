"""Handing a committed transfer job to the background consumer of its lane."""

import redis
from src.shared.redis_streams import (
    TRANSFER_JOB_ID_FIELD,
    TRANSFER_JOB_LIGHT_STREAM,
    TRANSFER_JOB_STREAM,
    TRANSFER_JOB_STREAM_MAXLEN,
)
from tables.models import TransferJob
from tables.services.redis_service import RedisService
from tables.services.transfer_jobs.export_definitions import TransferLane, export_definition

LANE_STREAMS = {
    TransferLane.HEAVY: TRANSFER_JOB_STREAM,
    TransferLane.LIGHT: TRANSFER_JOB_LIGHT_STREAM,
}


def job_lane(job: TransferJob) -> TransferLane:
    """The lane an export's definition names; imports (flows, collections) are heavy."""
    if job.kind == TransferJob.Kind.EXPORT:
        return export_definition(job.main_entity).lane
    return TransferLane.HEAVY


def enqueue_transfer_job(job: TransferJob, redis_client: redis.Redis | None = None) -> None:
    """Ask a django_app container to run `job`, on the stream of its lane.

    Call it from `transaction.on_commit`: the consumer must find the job row.
    """
    client = redis_client if redis_client is not None else RedisService().redis_client
    client.xadd(
        LANE_STREAMS[job_lane(job)],
        {TRANSFER_JOB_ID_FIELD: str(job.id)},
        maxlen=TRANSFER_JOB_STREAM_MAXLEN,
        approximate=True,
    )
