"""Handing a committed transfer job to the background consumer."""

import redis
from src.shared.redis_streams import (
    TRANSFER_JOB_ID_FIELD,
    TRANSFER_JOB_STREAM,
    TRANSFER_JOB_STREAM_MAXLEN,
)
from tables.models import TransferJob
from tables.services.redis_service import RedisService


def enqueue_transfer_job(job: TransferJob, redis_client: redis.Redis | None = None) -> None:
    """Ask a django_app container to run `job`.

    Call it from `transaction.on_commit`: the consumer must find the job row.
    """
    client = redis_client if redis_client is not None else RedisService().redis_client
    client.xadd(
        TRANSFER_JOB_STREAM,
        {TRANSFER_JOB_ID_FIELD: str(job.id)},
        maxlen=TRANSFER_JOB_STREAM_MAXLEN,
        approximate=True,
    )
