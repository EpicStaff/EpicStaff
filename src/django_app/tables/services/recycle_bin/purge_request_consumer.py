"""Runs the recycle-bin purge when manager asks for it through a Redis stream.

Manager owns the daily clock and adds one entry per run. All django_app containers read
the stream through one consumer group, so a request reaches exactly one of them.

Requests that piled up while the consumer was away are served by a single purge: the
purge is idempotent, so one run covers them all. Every entry of the batch is
acknowledged even when the purge failed; a failing purge must not be retried in a loop,
the next daily request retries it.

NOTE: an entry stays pending under the name of the consumer that read it. A container
recreated with a new hostname never re-reads entries its predecessor left pending
(a crash in the middle of a purge); the next daily request is served normally.
"""

import os
import socket
import time
from collections.abc import Callable

import redis
from django.conf import settings
from django.db import close_old_connections
from src.shared.redis_streams import (
    RECYCLE_BIN_PURGE_CONSUMER_GROUP,
    RECYCLE_BIN_PURGE_REQUESTED_AT_FIELD,
    RECYCLE_BIN_PURGE_STREAM,
)
from tables.services.recycle_bin.purge_service import PurgeService
from utils.logger import logger

READ_BLOCK_MILLISECONDS = 5000

# A read that hangs this long raises, so a half-open connection reaches run()'s backoff
# instead of blocking forever. Well above READ_BLOCK_MILLISECONDS.
REDIS_SOCKET_TIMEOUT_SECONDS = 30
REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30

MAX_RETRY_DELAY_SECONDS = 30

PENDING_BATCH_SIZE = 100


class RecycleBinPurgeRequestConsumer:
    """Reads purge requests through one consumer group and runs the purge for each batch."""

    def __init__(
        self,
        redis_client: redis.Redis,
        consumer_name: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.redis_client = redis_client
        self.consumer_name = consumer_name
        self._sleep = sleep

    @classmethod
    def from_settings(cls) -> "RecycleBinPurgeRequestConsumer":
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            username=settings.REDIS_USER,
            password=settings.REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_keepalive=True,
            health_check_interval=REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
        )
        return cls(redis_client=redis_client, consumer_name=socket.gethostname())

    def run(self) -> None:
        """Serve purge requests forever; after a Redis failure, wait (backing off) and start over."""
        logger.info(
            "Start worker {} consuming {} as {}",
            os.getpid(),
            RECYCLE_BIN_PURGE_STREAM,
            self.consumer_name,
        )
        consecutive_failures = 0
        while True:
            try:
                self.start()
                while True:
                    self.process_new(block_milliseconds=READ_BLOCK_MILLISECONDS)
                    consecutive_failures = 0
            except redis.RedisError:
                consecutive_failures += 1
                retry_delay = min(2 ** (consecutive_failures - 1), MAX_RETRY_DELAY_SECONDS)
                logger.exception(
                    "Recycle bin purge consumer lost Redis, starting over in {}s", retry_delay
                )
                self._sleep(retry_delay)

    def start(self) -> None:
        """Join the group, then serve the requests this consumer read but never acknowledged."""
        self._ensure_group()
        while pending := self.redis_client.xpending_range(
            RECYCLE_BIN_PURGE_STREAM,
            RECYCLE_BIN_PURGE_CONSUMER_GROUP,
            min="-",
            max="+",
            count=PENDING_BATCH_SIZE,
            consumername=self.consumer_name,
        ):
            pending_ids = [entry["message_id"] for entry in pending]
            entries = self.redis_client.xclaim(
                RECYCLE_BIN_PURGE_STREAM,
                RECYCLE_BIN_PURGE_CONSUMER_GROUP,
                self.consumer_name,
                min_idle_time=0,
                message_ids=pending_ids,
            )
            if entries:
                self._handle(entries)
            # An entry trimmed from the stream while pending is not returned by XCLAIM
            # on Redis < 7 and would stay pending; the loop would never end.
            self._acknowledge(pending_ids)

    def process_new(self, block_milliseconds: int | None) -> int:
        """Read one batch of new requests, serve it with one purge; return how many there were."""
        entries = self._read_new(block_milliseconds)
        if entries:
            self._handle(entries)
        return len(entries)

    def _ensure_group(self) -> None:
        # From id 0: a request added before the group existed is served too.
        try:
            self.redis_client.xgroup_create(
                RECYCLE_BIN_PURGE_STREAM, RECYCLE_BIN_PURGE_CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def _read_new(self, block_milliseconds: int | None) -> list:
        response = self.redis_client.xreadgroup(
            RECYCLE_BIN_PURGE_CONSUMER_GROUP,
            self.consumer_name,
            {RECYCLE_BIN_PURGE_STREAM: ">"},
            block=block_milliseconds,
        )
        if not response:
            return []
        [(_stream, entries)] = response
        return entries

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

    def _acknowledge(self, entry_ids: list[str]) -> None:
        self.redis_client.xack(
            RECYCLE_BIN_PURGE_STREAM, RECYCLE_BIN_PURGE_CONSUMER_GROUP, *entry_ids
        )
