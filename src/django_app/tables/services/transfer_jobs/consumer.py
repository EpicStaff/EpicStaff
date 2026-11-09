"""Runs transfer jobs and sweeps from the transfer-job streams, one consumer per lane.

Each entry is either one job to run or one sweep request from manager (on the
heavy stream only). Entries are
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
    TRANSFER_JOB_LIGHT_CONSUMER_GROUP,
    TRANSFER_JOB_LIGHT_STREAM,
    TRANSFER_JOB_STREAM,
    TRANSFER_JOB_SWEEP_REQUESTED_AT_FIELD,
)
from tables.services.stream_request_consumer import StreamRequestConsumer
from tables.services.transfer_jobs.export_definitions import TransferLane
from tables.services.transfer_jobs.runner import TransferJobRunner, sweep_transfer_jobs
from utils.logger import logger


class TransferJobConsumer(StreamRequestConsumer):
    """Serves the entries of one lane's stream, each read through the lane's consumer group.

    A subclass per lane names the stream and group; `LANE_CONSUMERS` maps lanes to them.
    """

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


class HeavyTransferJobConsumer(TransferJobConsumer):
    """Serves the heavy lane (large exports and every import) and the sweep requests."""

    stream = TRANSFER_JOB_STREAM
    group = TRANSFER_JOB_CONSUMER_GROUP
    description = "Heavy transfer job consumer"


class LightTransferJobConsumer(TransferJobConsumer):
    """Serves the light lane: small exports that should not wait behind a large one."""

    stream = TRANSFER_JOB_LIGHT_STREAM
    group = TRANSFER_JOB_LIGHT_CONSUMER_GROUP
    description = "Light transfer job consumer"


LANE_CONSUMERS: dict[TransferLane, type[TransferJobConsumer]] = {
    TransferLane.HEAVY: HeavyTransferJobConsumer,
    TransferLane.LIGHT: LightTransferJobConsumer,
}
