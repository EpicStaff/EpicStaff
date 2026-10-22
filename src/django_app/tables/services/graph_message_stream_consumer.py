"""Reads the graph message stream crew writes and hands each batch to ``GraphMessageStore``.

Delivery is at-least-once: an entry is acknowledged and deleted only after its batch
was stored, so a crash, a database outage or a Redis reconnect only delays messages.
The store makes a repeated batch harmless.

NOTE: exactly one consumer is assumed (the ``cache_redis`` process of the single
django_app container). The consumer is named after the host, so a restarted process
resumes its own pending entries at once. Entries a consumer under another name left
pending (a container recreated with a new hostname) are taken over once idle, by a check
that runs at start and then every ``STALE_ENTRY_IDLE_MILLISECONDS``; the same check
deletes consumers that stopped long ago, and warns about a second consumer that keeps
reading: two consumers split the stream between them and no longer store one session's
messages in order.

NOTE: needs Redis >= 7. Before 7.0, XCLAIM and XAUTOCLAIM reply nil for a pending entry
that was trimmed from the stream and keep it pending, and XAUTOCLAIM's reply has no
deleted-ids element; the trimmed-entry handling below relies on both.
"""

import os
import socket
import time
from collections.abc import Callable

import redis
from django.conf import settings
from django.db import (
    InterfaceError,
    OperationalError,
    close_old_connections,
    connection,
    reset_queries,
)
from src.shared.redis_streams import (
    GRAPH_MESSAGE_CONSUMER_GROUP,
    GRAPH_MESSAGE_ENVELOPE_TYPE,
    GRAPH_MESSAGE_STREAM,
)
from src.shared.redis_streams.graph_message_stream import DEFAULT_GRAPH_MESSAGE_STREAM_MAXLEN
from tables.services.graph_message_store import GraphMessageStore
from tables.utils.memory_trim import start_periodic_malloc_trim
from utils.logger import logger

READ_BLOCK_MILLISECONDS = 1000

# A read that hangs this long raises, so a half-open connection reaches run()'s backoff
# instead of blocking forever. Well above READ_BLOCK_MILLISECONDS, which a healthy
# blocking read takes.
REDIS_SOCKET_TIMEOUT_SECONDS = 10
REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30

# Entries another consumer (a replaced container) received but never acknowledged are
# taken over once idle this long; the takeover check runs this often.
STALE_ENTRY_IDLE_MILLISECONDS = 30_000

# Deleting a consumer drops its pending entries, so only one holding none is deleted, and
# only once idle far longer than a live consumer ever is (a blocking read, one batch, the
# longest backoff sleep).
DEAD_CONSUMER_IDLE_MILLISECONDS = 10 * 60_000

# Some database errors fail every retry of the same message (a cancelled query, a value
# past a Postgres limit). A batch delivered this often is stored one message at a time,
# and a message that still fails while the database answers is dropped.
MAX_DELIVERIES_BEFORE_ISOLATING = 10

# At the cap, crew trims messages that were never stored. Follows crew's default cap, not
# an overridden CREW_GRAPH_MESSAGE_STREAM_MAXLEN, which django_app does not see.
BACKLOG_WARNING_THRESHOLD = DEFAULT_GRAPH_MESSAGE_STREAM_MAXLEN // 2
BACKLOG_WARNING_INTERVAL_SECONDS = 60

MAX_RETRY_DELAY_SECONDS = 30

DATABASE_ERRORS = (OperationalError, InterfaceError)

# Retrying a batch after these can succeed, so its entries stay pending until it does.
TRANSIENT_ERRORS = (*DATABASE_ERRORS, redis.RedisError)


class GraphMessageStreamConsumer:
    """Consumes the graph message stream in batches, through one consumer group."""

    def __init__(
        self,
        redis_client: redis.Redis,
        store: GraphMessageStore,
        consumer_name: str,
        batch_size: int,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.redis_client = redis_client
        self.store = store
        self.consumer_name = consumer_name
        self.batch_size = batch_size
        self._sleep = sleep
        self._clock = clock
        self._last_backlog_warning_at: float | None = None
        self._last_recovery_at: float | None = None
        self._consumers_active_at_last_check: set[str] = set()

    @classmethod
    def from_settings(cls) -> "GraphMessageStreamConsumer":
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
        return cls(
            redis_client=redis_client,
            store=GraphMessageStore(redis_client),
            consumer_name=socket.gethostname(),
            batch_size=settings.GRAPH_MESSAGE_BATCH_SIZE,
        )

    def run(self) -> None:
        """Consume forever; after any failure, wait (backing off) and start over.

        Starting over re-reads this consumer's unacknowledged entries, so a batch that
        failed is retried until it is stored, or isolated and dropped after
        ``MAX_DELIVERIES_BEFORE_ISOLATING`` deliveries.
        """
        logger.info(
            "Start worker {} consuming {} as {}",
            os.getpid(),
            GRAPH_MESSAGE_STREAM,
            self.consumer_name,
        )
        start_periodic_malloc_trim()
        consecutive_failures = 0
        while True:
            try:
                self.start()
                consecutive_failures = 0
                while True:
                    self.process_new(block_milliseconds=READ_BLOCK_MILLISECONDS)
                    consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                retry_delay = min(2 ** (consecutive_failures - 1), MAX_RETRY_DELAY_SECONDS)
                logger.exception("Graph message consumer failed, starting over in {}s", retry_delay)
                self._sleep(retry_delay)

    def start(self) -> None:
        """Join the group, take over abandoned entries, then finish this consumer's own."""
        self._ensure_group()
        self._recover_abandoned_entries()
        self._process_own_pending_entries()

    def process_new(self, block_milliseconds: int | None) -> int:
        """Read and store one batch of new entries; return how many there were.

        Afterwards runs the periodic checks that are due: the takeover of abandoned
        entries (every ``STALE_ENTRY_IDLE_MILLISECONDS``) and the backlog warning.
        """
        entries = self._read_new(block_milliseconds)
        if entries:
            self._handle(entries)
        if self._recovery_is_due():
            self._recover_abandoned_entries()
        self._warn_on_backlog()
        return len(entries)

    def _ensure_group(self) -> None:
        # From id 0: entries crew added before the group existed are stored too.
        try:
            self.redis_client.xgroup_create(
                GRAPH_MESSAGE_STREAM, GRAPH_MESSAGE_CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    def _recovery_is_due(self) -> bool:
        return (
            self._last_recovery_at is None
            or (self._clock() - self._last_recovery_at) * 1000 >= STALE_ENTRY_IDLE_MILLISECONDS
        )

    def _recover_abandoned_entries(self) -> None:
        self._last_recovery_at = self._clock()
        self._take_over_stale_entries()
        self._review_other_consumers()

    def _take_over_stale_entries(self) -> None:
        cursor = "0-0"
        while True:
            start_id = cursor
            cursor, claimed_entries, trimmed_ids = self.redis_client.xautoclaim(
                GRAPH_MESSAGE_STREAM,
                GRAPH_MESSAGE_CONSUMER_GROUP,
                self.consumer_name,
                min_idle_time=STALE_ENTRY_IDLE_MILLISECONDS,
                start_id=start_id,
                count=self.batch_size,
            )
            if trimmed_ids:
                # XAUTOCLAIM already removed these from the pending list.
                self._log_trimmed(trimmed_ids)
            if claimed_entries:
                logger.warning("Took over {} unacknowledged graph messages", len(claimed_entries))
                self._handle(claimed_entries)
            # Redis returns "0-0" once the whole pending list is scanned. A cursor that
            # did not move also ends the scan (fakeredis returns the start id instead).
            if cursor in ("0-0", start_id):
                return

    def _review_other_consumers(self) -> None:
        # A consumer seen active at two checks in a row is really reading. One seen only
        # once may be the container this one replaced, stopped just before it started.
        active_consumers = set()
        for consumer in self.redis_client.xinfo_consumers(
            GRAPH_MESSAGE_STREAM, GRAPH_MESSAGE_CONSUMER_GROUP
        ):
            name = consumer["name"]
            if name == self.consumer_name:
                continue
            if consumer["idle"] < STALE_ENTRY_IDLE_MILLISECONDS:
                active_consumers.add(name)
            elif consumer["idle"] >= DEAD_CONSUMER_IDLE_MILLISECONDS and consumer["pending"] == 0:
                self.redis_client.xgroup_delconsumer(
                    GRAPH_MESSAGE_STREAM, GRAPH_MESSAGE_CONSUMER_GROUP, name
                )
                logger.info("Deleted graph message consumer {}, idle {} ms", name, consumer["idle"])
        for name in sorted(active_consumers & self._consumers_active_at_last_check):
            logger.warning(
                "Consumer {} also reads {}: graph messages are split between consumers "
                "and one session's messages may be stored out of order. Run a single "
                "cache_redis process.",
                name,
                GRAPH_MESSAGE_STREAM,
            )
        self._consumers_active_at_last_check = active_consumers

    def _process_own_pending_entries(self) -> None:
        # XCLAIM to itself rather than XREADGROUP from id 0: a history read returns an
        # entry trimmed from the stream while pending with empty fields, which looks like
        # a malformed entry, while XCLAIM leaves it out of the reply and drops it from the
        # pending list, so it is reported as lost.
        while pending := self.redis_client.xpending_range(
            GRAPH_MESSAGE_STREAM,
            GRAPH_MESSAGE_CONSUMER_GROUP,
            min="-",
            max="+",
            count=self.batch_size,
            consumername=self.consumer_name,
        ):
            pending_ids = [entry["message_id"] for entry in pending]
            most_deliveries = max(entry["times_delivered"] for entry in pending)
            entries = self.redis_client.xclaim(
                GRAPH_MESSAGE_STREAM,
                GRAPH_MESSAGE_CONSUMER_GROUP,
                self.consumer_name,
                min_idle_time=0,
                message_ids=pending_ids,
            )
            returned_ids = {entry_id for entry_id, _fields in entries}
            trimmed_ids = [entry_id for entry_id in pending_ids if entry_id not in returned_ids]
            if trimmed_ids:
                self._log_trimmed(trimmed_ids)
                self._acknowledge(trimmed_ids)
            if entries:
                self._handle(
                    entries,
                    isolate_failures=most_deliveries >= MAX_DELIVERIES_BEFORE_ISOLATING,
                )

    def _read_new(self, block_milliseconds: int | None) -> list:
        response = self.redis_client.xreadgroup(
            GRAPH_MESSAGE_CONSUMER_GROUP,
            self.consumer_name,
            {GRAPH_MESSAGE_STREAM: ">"},
            count=self.batch_size,
            block=block_milliseconds,
        )
        if not response:
            return []
        [(_stream, entries)] = response
        return entries

    def _handle(self, entries: list, isolate_failures: bool = False) -> None:
        close_old_connections()
        try:
            payloads = [
                payload
                for entry_id, fields in entries
                if (payload := self._payload_of(entry_id, fields)) is not None
            ]
            if isolate_failures:
                logger.warning(
                    "Storing {} graph messages one by one: delivered {} times or more "
                    "without being stored",
                    len(payloads),
                    MAX_DELIVERIES_BEFORE_ISOLATING,
                )
                for payload in payloads:
                    self._persist_alone(payload, drop_on_database_error=True)
            else:
                try:
                    self.store.persist_batch(payloads)
                except TRANSIENT_ERRORS:
                    raise
                except Exception:
                    logger.exception("Graph message batch failed; storing its messages one by one")
                    for payload in payloads:
                        self._persist_alone(payload)
            self._acknowledge([entry_id for entry_id, _fields in entries])
        finally:
            # With DEBUG on, Django keeps every executed query, parameters included, in
            # connection.queries_log; only the HTTP request cycle clears it, and this
            # worker has none, so every stored 300 KB message would stay in memory.
            reset_queries()

    def _persist_alone(self, payload: str, drop_on_database_error: bool = False) -> None:
        try:
            self.store.persist_batch([payload])
        except DATABASE_ERRORS:
            # The database not answering is an outage: keep the message for a retry.
            if not (drop_on_database_error and self._database_answers()):
                raise
            logger.exception("Dropping a graph message that fails with a database error")
        except redis.RedisError:
            raise
        except Exception:
            logger.exception("Dropping a graph message that cannot be stored")

    @staticmethod
    def _database_answers() -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DATABASE_ERRORS:
            return False
        return True

    @staticmethod
    def _payload_of(entry_id: str, fields: dict | None) -> str | None:
        if not fields or fields.get("type") != GRAPH_MESSAGE_ENVELOPE_TYPE:
            logger.error("Skipping stream entry {}: not a graph message envelope", entry_id)
            return None
        return fields.get("payload")

    @staticmethod
    def _log_trimmed(entry_ids: list[str]) -> None:
        logger.error(
            "{} pending graph messages were trimmed from the stream before being stored",
            len(entry_ids),
        )

    def _acknowledge(self, entry_ids: list[str]) -> None:
        # Deleted as well as acknowledged, so the stream only holds what is not stored
        # yet and its length is the backlog. One MULTI: never one without the other.
        pipeline = self.redis_client.pipeline(transaction=True)
        pipeline.xack(GRAPH_MESSAGE_STREAM, GRAPH_MESSAGE_CONSUMER_GROUP, *entry_ids)
        pipeline.xdel(GRAPH_MESSAGE_STREAM, *entry_ids)
        pipeline.execute()

    def _warn_on_backlog(self) -> None:
        now = self._clock()
        if (
            self._last_backlog_warning_at is not None
            and now - self._last_backlog_warning_at < BACKLOG_WARNING_INTERVAL_SECONDS
        ):
            return
        backlog = self.redis_client.xlen(GRAPH_MESSAGE_STREAM)
        if backlog > BACKLOG_WARNING_THRESHOLD:
            self._last_backlog_warning_at = now
            logger.warning(
                "{} graph messages are waiting to be stored; past crew's "
                "GRAPH_MESSAGE_STREAM_MAXLEN the oldest are dropped",
                backlog,
            )
