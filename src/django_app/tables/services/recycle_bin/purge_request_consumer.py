"""Runs the recycle-bin purge when manager asks for it through a Redis stream.

Manager owns the daily clock and adds one entry per run. All django_app containers read
the stream through one consumer group, so a request reaches exactly one of them.

Requests that piled up while the consumer was away are served by a single purge: the
purge is idempotent, so one run covers them all. Every entry of the batch is
acknowledged even when the purge failed; a failing purge must not be retried in a loop,
the next daily request retries it.
"""

from django.db import close_old_connections
from src.shared.redis_streams import (
    RECYCLE_BIN_PURGE_CONSUMER_GROUP,
    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD,
    RECYCLE_BIN_PURGE_STREAM,
)
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.stream_request_consumer import StreamRequestConsumer
from utils.logger import logger


class RecycleBinPurgeRequestConsumer(StreamRequestConsumer):
    """Reads purge requests through one consumer group and runs the purge for each batch."""

    stream = RECYCLE_BIN_PURGE_STREAM
    group = RECYCLE_BIN_PURGE_CONSUMER_GROUP
    description = "Recycle bin purge consumer"

    def _handle(self, entries: list) -> None:
        requested_at = [
            fields[RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD]
            for _entry_id, fields in entries
            if fields and RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD in fields
        ]
        logger.info(
            "Recycle bin purge started for {} request(s), requested at {}",
            len(entries),
            requested_at,
        )
        try:
            close_old_connections()
            counts = PurgeService.purge_expired()
            if counts:
                logger.info(
                    "Recycle bin purge finished: {} row(s) purged ({})",
                    sum(counts.values()),
                    counts,
                )
            else:
                logger.info("Recycle bin purge finished: nothing to purge")
        except Exception:
            logger.exception("Recycle bin purge failed")
        finally:
            try:
                close_old_connections()
            except Exception:
                logger.exception("Closing stale database connections failed")
            finally:
                self._acknowledge([entry_id for entry_id, _fields in entries])
