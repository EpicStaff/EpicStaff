"""Reading a Redis stream of requests through one consumer group.

Every django_app container reads the stream through the same group, so an entry
reaches exactly one of them. A subclass says which stream and group, and what
to do with a batch of entries; it must acknowledge every entry it was handed.

NOTE: an entry stays pending under the name of the consumer that read it. A
container recreated with a new hostname never re-reads entries its predecessor
left pending.
"""

import os
import socket
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Self

import redis
from django.conf import settings
from utils.logger import logger

READ_BLOCK_MILLISECONDS = 5000

# A read that hangs this long raises, so a half-open connection reaches run()'s backoff
# instead of blocking forever. Well above READ_BLOCK_MILLISECONDS.
REDIS_SOCKET_TIMEOUT_SECONDS = 30
REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30

MAX_RETRY_DELAY_SECONDS = 30

PENDING_BATCH_SIZE = 100


class StreamRequestConsumer(ABC):
    """Reads requests through one consumer group and hands each batch to `_handle`."""

    stream: str
    group: str
    # How the consumer names itself in log messages.
    description: str
    # Entries read per XREADGROUP; None lets Redis return everything new. A consumer
    # whose entries take long sets 1, so the others are left for other containers.
    read_count: int | None = None

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
    def from_settings(cls, **kwargs) -> Self:
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
        return cls(redis_client=redis_client, consumer_name=socket.gethostname(), **kwargs)

    def run(self) -> None:
        """Serve requests forever; after a Redis failure, wait (backing off) and start over."""
        logger.info(
            "Start worker {} consuming {} as {}", os.getpid(), self.stream, self.consumer_name
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
                    "{} lost Redis, starting over in {}s", self.description, retry_delay
                )
                self._sleep(retry_delay)

    def start(self) -> None:
        """Join the group, then serve the requests this consumer read but never acknowledged."""
        self._ensure_group()
        while pending := self.redis_client.xpending_range(
            self.stream,
            self.group,
            min="-",
            max="+",
            count=PENDING_BATCH_SIZE,
            consumername=self.consumer_name,
        ):
            pending_ids = [entry["message_id"] for entry in pending]
            entries = self.redis_client.xclaim(
                self.stream,
                self.group,
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
        """Read one batch of new requests and serve it; return how many there were."""
        entries = self._read_new(block_milliseconds)
        if entries:
            self._handle(entries)
        return len(entries)

    @abstractmethod
    def _handle(self, entries: list) -> None:
        """Serve one batch of `(entry id, fields)` and acknowledge every entry of it."""

    def _ensure_group(self) -> None:
        # From id 0: a request added before the group existed is served too.
        try:
            self.redis_client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def _read_new(self, block_milliseconds: int | None) -> list:
        response = self.redis_client.xreadgroup(
            self.group,
            self.consumer_name,
            {self.stream: ">"},
            count=self.read_count,
            block=block_milliseconds,
        )
        if not response:
            return []
        [(_stream, entries)] = response
        return entries

    def _acknowledge(self, entry_ids: list[str]) -> None:
        self.redis_client.xack(self.stream, self.group, *entry_ids)
