import json
import socket
import time
from collections import Counter
from uuid import uuid4

import fakeredis
import pytest
import redis
from django.db import OperationalError, connection

from src.shared.redis_streams import graph_message_fields
from tables.models.graph_models import Graph, GraphSessionMessage
from tables.models.session_models import Session
from tables.services import graph_message_stream_consumer
from tables.services.graph_message_store import GraphMessageStore
from tables.services.graph_message_stream_consumer import (
    BACKLOG_WARNING_THRESHOLD,
    MAX_DELIVERIES_BEFORE_ISOLATING,
    GraphMessageStreamConsumer,
)
from utils.logger import logger

pytestmark = pytest.mark.django_db

STREAM = "graph.messages"
GROUP = "django-graph-message-store"


class DeliveryCountingRedis(fakeredis.FakeRedis):
    """fakeredis 2.32 keeps no per-entry delivery count; this adds the one Redis keeps.

    Like Redis, a delivery is counted when XREADGROUP hands out a new entry and when
    XCLAIM or XAUTOCLAIM claims one, and XPENDING reports it as ``times_delivered``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deliveries = Counter()

    def xreadgroup(self, *args, **kwargs):
        response = super().xreadgroup(*args, **kwargs)
        for _stream, entries in response or []:
            self._count(entries)
        return response

    def xclaim(self, *args, **kwargs):
        entries = super().xclaim(*args, **kwargs)
        self._count(entries)
        return entries

    def xautoclaim(self, *args, **kwargs):
        response = super().xautoclaim(*args, **kwargs)
        self._count(response[1])
        return response

    def xpending_range(self, *args, **kwargs):
        return [
            {**entry, "times_delivered": self.deliveries[entry["message_id"]]}
            for entry in super().xpending_range(*args, **kwargs)
        ]

    def _count(self, entries):
        for entry_id, _fields in entries:
            self.deliveries[entry_id] += 1


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _StopRunning(BaseException):
    """Not an Exception, so run()'s start-over loop does not catch it."""


@pytest.fixture
def redis_server():
    yield fakeredis.FakeServer()


@pytest.fixture
def redis_client(monkeypatch, redis_server):
    # close_old_connections() would drop the test's transactional DB connection.
    monkeypatch.setattr(graph_message_stream_consumer, "close_old_connections", lambda: None)
    client = DeliveryCountingRedis(server=redis_server, decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def clock():
    yield FakeClock()


@pytest.fixture
def warnings_logged():
    messages = []
    handler_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(handler_id)


def _consumer(redis_client, name="django-host-1", **kwargs):
    return GraphMessageStreamConsumer(
        redis_client=redis_client,
        store=GraphMessageStore(redis_client),
        consumer_name=name,
        batch_size=50,
        **kwargs,
    )


@pytest.fixture
def session(default_org):
    graph = Graph.objects.create(name="graph-message-consumer", org=default_org)
    yield Session.objects.create(graph=graph, status=Session.SessionStatus.RUN, variables={})


def _add(redis_client, session_id, text="hello"):
    message = {
        "session_id": session_id,
        "name": "node",
        "execution_order": 1,
        "timestamp": "2026-10-05T10:00:00+00:00",
        "message_data": {"message_type": "agent", "text": text},
        "uuid": str(uuid4()),
    }
    redis_client.xadd(STREAM, graph_message_fields(message))
    return message["uuid"]


def _stored_uuids(session):
    return [
        str(stored_uuid)
        for stored_uuid in GraphSessionMessage.objects.filter(session=session)
        .order_by("id")
        .values_list("uuid", flat=True)
    ]


def _pending_count(redis_client):
    return redis_client.xpending(STREAM, GROUP)["pending"]


def _consumer_names(redis_client):
    return sorted(consumer["name"] for consumer in redis_client.xinfo_consumers(STREAM, GROUP))


def _database_down(payloads):
    raise OperationalError("server closed the connection unexpectedly")


def _failing_on_poison(persist_batch, error):
    def persist(payloads):
        if any(json.loads(payload)["message_data"]["text"] == "poison" for payload in payloads):
            raise error
        persist_batch(payloads)

    return persist


def test_stored_entries_are_acknowledged_and_deleted(redis_client, session):
    consumer = _consumer(redis_client)
    consumer.start()
    uuids = [_add(redis_client, session.id, text=str(index)) for index in range(3)]

    processed = consumer.process_new(block_milliseconds=None)

    assert processed == 3
    assert _stored_uuids(session) == uuids
    assert redis_client.xlen(STREAM) == 0
    assert _pending_count(redis_client) == 0


def test_entries_added_before_the_consumer_group_existed_are_stored(redis_client, session):
    uuid = _add(redis_client, session.id)
    consumer = _consumer(redis_client)

    consumer.start()
    consumer.process_new(block_milliseconds=None)

    assert _stored_uuids(session) == [uuid]
    assert redis_client.xlen(STREAM) == 0


def test_database_outage_leaves_the_batch_pending_until_a_restart_stores_it(
    redis_client, session, monkeypatch
):
    consumer = _consumer(redis_client)
    consumer.start()
    uuid = _add(redis_client, session.id)
    monkeypatch.setattr(consumer.store, "persist_batch", _database_down)
    with pytest.raises(OperationalError):
        consumer.process_new(block_milliseconds=None)
    pending_during_outage = _pending_count(redis_client)
    monkeypatch.undo()
    monkeypatch.setattr(graph_message_stream_consumer, "close_old_connections", lambda: None)

    # run() starts over after a failure: start() re-reads this consumer's pending entries.
    consumer.start()

    assert pending_during_outage == 1
    assert _stored_uuids(session) == [uuid]
    assert redis_client.xlen(STREAM) == 0
    assert _pending_count(redis_client) == 0


def test_entries_of_a_replaced_container_are_taken_over_once_idle_while_consuming(
    redis_client, session, clock, monkeypatch, warnings_logged
):
    monkeypatch.setattr(graph_message_stream_consumer, "STALE_ENTRY_IDLE_MILLISECONDS", 200)
    replaced_container = _consumer(redis_client, name="replaced-container")
    replaced_container.start()
    uuid = _add(redis_client, session.id)
    # The replaced container received the entry but never stored or acknowledged it.
    redis_client.xreadgroup(GROUP, "replaced-container", {STREAM: ">"}, count=50)
    new_container = _consumer(redis_client, name="new-container", clock=clock)

    new_container.start()
    stored_while_entry_was_fresh = _stored_uuids(session)
    time.sleep(0.25)
    new_container.process_new(block_milliseconds=None)
    stored_before_takeover_was_due = _stored_uuids(session)
    clock.advance(0.2)
    new_container.process_new(block_milliseconds=None)

    assert stored_while_entry_was_fresh == []
    assert stored_before_takeover_was_due == []
    assert _stored_uuids(session) == [uuid]
    assert redis_client.xlen(STREAM) == 0
    assert _pending_count(redis_client) == 0
    assert not any("also reads" in warning for warning in warnings_logged)


def test_entry_of_a_replaced_container_trimmed_while_pending_does_not_block_takeover(
    redis_client, session, clock, monkeypatch
):
    monkeypatch.setattr(graph_message_stream_consumer, "STALE_ENTRY_IDLE_MILLISECONDS", 100)
    _consumer(redis_client, name="replaced-container").start()
    _add(redis_client, session.id)
    redis_client.xreadgroup(GROUP, "replaced-container", {STREAM: ">"}, count=50)
    # Crew's MAXLEN trims the entry while it is still pending.
    redis_client.xtrim(STREAM, maxlen=0)
    uuid = _add(redis_client, session.id)
    time.sleep(0.15)

    new_container = _consumer(redis_client, name="new-container", clock=clock)
    new_container.start()
    new_container.process_new(block_milliseconds=None)

    assert _stored_uuids(session) == [uuid]
    assert _pending_count(redis_client) == 0


def test_dead_consumer_is_deleted_once_idle_long_enough(redis_client, session, clock, monkeypatch):
    monkeypatch.setattr(graph_message_stream_consumer, "STALE_ENTRY_IDLE_MILLISECONDS", 100)
    monkeypatch.setattr(graph_message_stream_consumer, "DEAD_CONSUMER_IDLE_MILLISECONDS", 300)
    stopped_container = _consumer(redis_client, name="stopped-container")
    stopped_container.start()
    _add(redis_client, session.id)
    stopped_container.process_new(block_milliseconds=None)
    new_container = _consumer(redis_client, name="new-container", clock=clock)

    new_container.start()
    consumers_while_recently_active = _consumer_names(redis_client)
    time.sleep(0.35)
    clock.advance(0.1)
    new_container.process_new(block_milliseconds=None)

    assert "stopped-container" in consumers_while_recently_active
    assert _consumer_names(redis_client) == ["new-container"]


def test_consumer_holding_pending_entries_is_never_deleted(redis_client, session, monkeypatch):
    # Entries this fresh are not taken over yet, while the consumer is idle past the
    # dead threshold: deleting it would lose them.
    monkeypatch.setattr(graph_message_stream_consumer, "STALE_ENTRY_IDLE_MILLISECONDS", 10_000)
    monkeypatch.setattr(graph_message_stream_consumer, "DEAD_CONSUMER_IDLE_MILLISECONDS", 100)
    _consumer(redis_client, name="stopped-container").start()
    _add(redis_client, session.id)
    redis_client.xreadgroup(GROUP, "stopped-container", {STREAM: ">"}, count=50)
    time.sleep(0.15)

    _consumer(redis_client, name="new-container").start()

    assert "stopped-container" in _consumer_names(redis_client)
    assert redis_client.xpending(STREAM, GROUP)["consumers"] == [
        {"name": "stopped-container", "pending": 1}
    ]


def test_consumer_that_keeps_reading_is_reported_from_the_second_check(
    redis_client, session, clock, warnings_logged
):
    other_container = _consumer(redis_client, name="other-container")
    other_container.start()
    other_container.process_new(block_milliseconds=None)
    this_container = _consumer(redis_client, name="this-container", clock=clock)

    this_container.start()
    warned_at_first_check = any("other-container also reads" in w for w in warnings_logged)
    clock.advance(30)
    other_container.process_new(block_milliseconds=None)
    this_container.process_new(block_milliseconds=None)

    assert not warned_at_first_check
    assert any("Consumer other-container also reads" in w for w in warnings_logged)


def test_pending_entry_trimmed_from_the_stream_does_not_block_a_restart(
    redis_client, session, monkeypatch
):
    consumer = _consumer(redis_client)
    consumer.start()
    _add(redis_client, session.id)
    monkeypatch.setattr(consumer.store, "persist_batch", _database_down)
    with pytest.raises(OperationalError):
        consumer.process_new(block_milliseconds=None)
    monkeypatch.undo()
    monkeypatch.setattr(graph_message_stream_consumer, "close_old_connections", lambda: None)
    # Crew's MAXLEN trims the entry while it is still pending.
    redis_client.xtrim(STREAM, maxlen=0)
    uuid = _add(redis_client, session.id)

    consumer.start()
    consumer.process_new(block_milliseconds=None)

    assert _stored_uuids(session) == [uuid]
    assert _pending_count(redis_client) == 0


def test_entry_that_is_not_a_graph_message_is_dropped(redis_client, session):
    consumer = _consumer(redis_client)
    consumer.start()
    redis_client.xadd(STREAM, {"type": "something.else", "correlation_id": "x", "payload": "{}"})
    uuid = _add(redis_client, session.id)

    consumer.process_new(block_milliseconds=None)

    assert _stored_uuids(session) == [uuid]
    assert redis_client.xlen(STREAM) == 0


def test_message_that_breaks_its_batch_is_dropped_alone(redis_client, session, monkeypatch):
    consumer = _consumer(redis_client)
    consumer.start()
    first_uuid = _add(redis_client, session.id, text="first")
    _add(redis_client, session.id, text="poison")
    last_uuid = _add(redis_client, session.id, text="last")
    monkeypatch.setattr(
        consumer.store,
        "persist_batch",
        _failing_on_poison(consumer.store.persist_batch, ValueError("a bug in storing it")),
    )

    consumer.process_new(block_milliseconds=None)

    assert _stored_uuids(session) == [first_uuid, last_uuid]
    assert redis_client.xlen(STREAM) == 0


def test_message_failing_with_a_database_error_on_every_delivery_is_dropped_alone(
    redis_client, session, monkeypatch
):
    consumer = _consumer(redis_client)
    consumer.start()
    first_uuid = _add(redis_client, session.id, text="first")
    _add(redis_client, session.id, text="poison")
    last_uuid = _add(redis_client, session.id, text="last")
    monkeypatch.setattr(
        consumer.store,
        "persist_batch",
        _failing_on_poison(
            consumer.store.persist_batch,
            OperationalError("canceling statement due to statement timeout"),
        ),
    )
    with pytest.raises(OperationalError):
        consumer.process_new(block_milliseconds=None)
    failed_restarts = 0
    for _restart in range(MAX_DELIVERIES_BEFORE_ISOLATING + 5):
        try:
            consumer.start()
            break
        except OperationalError:
            failed_restarts += 1

    # The first read was delivery 1; each failed restart redelivered the batch once more.
    assert failed_restarts == MAX_DELIVERIES_BEFORE_ISOLATING - 1
    assert _stored_uuids(session) == [first_uuid, last_uuid]
    assert redis_client.xlen(STREAM) == 0
    assert _pending_count(redis_client) == 0


def test_database_outage_past_the_delivery_cap_drops_nothing(redis_client, session, monkeypatch):
    class UnreachableDatabase:
        def cursor(self):
            raise OperationalError("could not connect to server")

    consumer = _consumer(redis_client)
    consumer.start()
    uuid = _add(redis_client, session.id)
    monkeypatch.setattr(consumer.store, "persist_batch", _database_down)
    monkeypatch.setattr(graph_message_stream_consumer, "connection", UnreachableDatabase())
    with pytest.raises(OperationalError):
        consumer.process_new(block_milliseconds=None)
    for _restart in range(MAX_DELIVERIES_BEFORE_ISOLATING + 2):
        with pytest.raises(OperationalError):
            consumer.start()
    pending_during_outage = _pending_count(redis_client)
    monkeypatch.undo()
    monkeypatch.setattr(graph_message_stream_consumer, "close_old_connections", lambda: None)

    consumer.start()

    assert pending_during_outage == 1
    assert _stored_uuids(session) == [uuid]
    assert redis_client.xlen(STREAM) == 0


def test_query_log_is_cleared_after_each_batch(redis_client, session, settings):
    settings.DEBUG = True
    consumer = _consumer(redis_client)
    consumer.start()
    uuid = _add(redis_client, session.id, text="x" * 10_000)

    consumer.process_new(block_milliseconds=None)
    queries_kept_after_batch = list(connection.queries_log)

    assert _stored_uuids(session) == [uuid]
    assert queries_kept_after_batch == []


def test_run_backs_off_exponentially_up_to_the_cap_while_redis_is_down(
    redis_client, redis_server, monkeypatch
):
    monkeypatch.setattr(graph_message_stream_consumer, "start_periodic_malloc_trim", lambda: None)
    redis_server.connected = False
    delays = []

    def sleep(seconds):
        delays.append(seconds)
        if len(delays) == 7:
            raise _StopRunning

    with pytest.raises(_StopRunning):
        _consumer(redis_client, sleep=sleep).run()

    assert delays == [1, 2, 4, 8, 16, 30, 30]


def test_run_resets_the_backoff_after_it_recovers(
    redis_client, redis_server, session, monkeypatch
):
    monkeypatch.setattr(graph_message_stream_consumer, "start_periodic_malloc_trim", lambda: None)
    uuid = _add(redis_client, session.id)
    redis_server.connected = False
    delays = []

    def sleep(seconds):
        delays.append(seconds)
        if len(delays) == 2:
            redis_server.connected = True
        if len(delays) == 3:
            raise _StopRunning

    consumer = _consumer(redis_client, sleep=sleep)
    persist_batch = consumer.store.persist_batch

    def persist_then_lose_redis(payloads):
        persist_batch(payloads)
        redis_server.connected = False

    monkeypatch.setattr(consumer.store, "persist_batch", persist_then_lose_redis)

    with pytest.raises(_StopRunning):
        consumer.run()

    assert delays == [1, 2, 1]
    assert _stored_uuids(session) == [uuid]


def test_backlog_warning_is_logged_at_most_once_per_interval(
    redis_client, clock, warnings_logged
):
    pipeline = redis_client.pipeline()
    for index in range(BACKLOG_WARNING_THRESHOLD + 1):
        pipeline.xadd(STREAM, {"index": index})
    pipeline.execute()
    consumer = _consumer(redis_client, clock=clock)

    def backlog_warnings():
        return sum("waiting to be stored" in warning for warning in warnings_logged)

    consumer._warn_on_backlog()
    after_first_check = backlog_warnings()
    clock.advance(30)
    consumer._warn_on_backlog()
    within_interval = backlog_warnings()
    clock.advance(30)
    consumer._warn_on_backlog()
    after_interval = backlog_warnings()
    redis_client.xtrim(STREAM, maxlen=BACKLOG_WARNING_THRESHOLD)
    clock.advance(60)
    consumer._warn_on_backlog()

    assert (after_first_check, within_interval, after_interval) == (1, 1, 2)
    assert backlog_warnings() == 2


def test_redis_client_raises_instead_of_hanging_on_a_silent_server(settings, monkeypatch):
    # Accepts the TCP connection (kernel backlog) but never answers, like a half-open peer.
    silent_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    silent_server.bind(("127.0.0.1", 0))
    silent_server.listen()
    settings.REDIS_HOST, settings.REDIS_PORT = silent_server.getsockname()
    monkeypatch.setattr(graph_message_stream_consumer, "REDIS_SOCKET_TIMEOUT_SECONDS", 0.2)
    consumer = GraphMessageStreamConsumer.from_settings()
    connection_settings = consumer.redis_client.connection_pool.connection_kwargs
    try:
        started_at = time.monotonic()
        with pytest.raises(redis.TimeoutError):
            consumer.redis_client.ping()
        waited = time.monotonic() - started_at
    finally:
        consumer.redis_client.close()
        silent_server.close()

    assert waited < 2
    assert connection_settings["socket_keepalive"] is True
    assert connection_settings["health_check_interval"] > 0
    assert consumer.consumer_name == socket.gethostname()
