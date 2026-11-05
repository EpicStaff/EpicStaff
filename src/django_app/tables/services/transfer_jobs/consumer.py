"""Runs transfer jobs and sweeps from the transfer-job stream.

Each entry is either one job to run or one sweep request from manager. Entries are
served one at a time and acknowledged one at a time, so a container stopped mid-batch
leaves only the unserved ones pending. A job that fails is not retried: it ends
`failed` with a reason its creator sees.
"""

from uuid import UUID

from django.db import close_old_connections
from django.utils import timezone
from src.shared.redis_streams import (
    TRANSFER_JOB_CONSUMER_GROUP,
    TRANSFER_JOB_ID_FIELD,
    TRANSFER_JOB_STREAM,
    TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD,
)
from tables.services.stream_request_consumer import StreamRequestConsumer
from tables.services.transfer_jobs.runner import TransferJobRunner, sweep_transfer_jobs
from utils.logger import logger


class TransferJobConsumer(StreamRequestConsumer):
    """Reads transfer-job entries through one consumer group and serves each of them."""

    stream = TRANSFER_JOB_STREAM
    group = TRANSFER_JOB_CONSUMER_GROUP
    description = "Transfer job consumer"
    # A job can run for minutes; a batch read here would hold the rest of it pending
    # behind that job instead of letting another container take it.
    read_count = 1

    def __init__(self, *args, runner: TransferJobRunner | None = None, sweep=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._runner = runner
        self._sweep = sweep if sweep is not None else sweep_transfer_jobs

    def _handle(self, entries: list) -> None:
        for entry_id, fields in entries:
            try:
                close_old_connections()
                self._serve(fields or {})
            except Exception:
                logger.exception("Transfer job entry {} failed", entry_id)
            finally:
                self._acknowledge([entry_id])

    def _serve(self, fields: dict) -> None:
        if TRANSFER_JOB_ID_FIELD in fields:
            runner = self._runner if self._runner is not None else TransferJobRunner()
            runner.run(UUID(fields[TRANSFER_JOB_ID_FIELD]))
        elif TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD in fields:
            counts = self._sweep(timezone.now())
            logger.info(
                "Transfer job sweep requested at {}: {}",
                fields[TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD],
                counts,
            )
        else:
            logger.warning("Transfer job entry without a job or a sweep: {}", fields)
