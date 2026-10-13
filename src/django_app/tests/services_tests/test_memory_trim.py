import sys
import threading

import fakeredis
import pytest

from tables.services import redis_pubsub
from tables.services.graph_message_stream_consumer import GraphMessageStreamConsumer
from tables.utils import memory_trim


class _ParkingFakeLibc:
    """Records malloc_trim calls, then parks the calling thread for good.

    The trim thread is a daemon with no stop switch, so parking it on the first
    call keeps it from trimming (or logging) again for the rest of the test run.
    """

    def __init__(self):
        self.trim_arguments = []
        self.trimmed = threading.Event()
        self._never_released = threading.Event()

    def malloc_trim(self, pad):
        self.trim_arguments.append(pad)
        self.trimmed.set()
        self._never_released.wait()


@pytest.fixture
def fake_libc(monkeypatch, settings):
    fake = _ParkingFakeLibc()
    monkeypatch.setattr(memory_trim, "_libc", fake)
    monkeypatch.setattr(memory_trim, "_trim_thread", None)
    settings.MALLOC_TRIM_INTERVAL = 3600
    yield fake


def test_repeated_starts_run_one_daemon_thread(fake_libc):
    memory_trim.start_periodic_malloc_trim()
    first_thread = memory_trim._trim_thread

    memory_trim.start_periodic_malloc_trim()

    assert memory_trim._trim_thread is first_thread
    assert first_thread.is_alive()
    assert first_thread.daemon


def test_concurrent_starts_run_one_thread(fake_libc):
    started_threads = []

    def start_and_record():
        memory_trim.start_periodic_malloc_trim()
        started_threads.append(memory_trim._trim_thread)

    callers = [threading.Thread(target=start_and_record) for _ in range(8)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join()

    assert len({id(thread) for thread in started_threads}) == 1


def test_thread_trims_once_the_interval_elapses(fake_libc, settings):
    settings.MALLOC_TRIM_INTERVAL = 0.01

    memory_trim.start_periodic_malloc_trim()

    assert fake_libc.trimmed.wait(timeout=5)
    assert fake_libc.trim_arguments == [0]


def test_dead_thread_is_replaced(fake_libc):
    finished_thread = threading.Thread(target=lambda: None)
    finished_thread.start()
    finished_thread.join()
    memory_trim._trim_thread = finished_thread

    memory_trim.start_periodic_malloc_trim()

    assert memory_trim._trim_thread is not finished_thread
    assert memory_trim._trim_thread.is_alive()


def test_interval_none_starts_nothing(fake_libc, settings):
    settings.MALLOC_TRIM_INTERVAL = None

    memory_trim.start_periodic_malloc_trim()

    assert memory_trim._trim_thread is None


def test_missing_glibc_starts_nothing(fake_libc, monkeypatch):
    monkeypatch.setattr(memory_trim, "_libc", None)

    memory_trim.start_periodic_malloc_trim()

    assert memory_trim._trim_thread is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_read_rss_mb_reports_this_process():
    assert memory_trim.read_rss_mb() > 0


def test_redis_listener_starts_the_trim_thread(fake_libc, monkeypatch):
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub,
        "_create_redis_client",
        lambda self: fakeredis.FakeRedis(decode_responses=True),
    )
    pubsub = redis_pubsub.RedisPubSub()
    # The reconnect loop never returns; the trim thread must already be running by then.
    monkeypatch.setattr(pubsub, "_run_with_reconnect", lambda label, inner_loop: None)

    pubsub.listen_for_redis_messages_worker()

    assert memory_trim._trim_thread is not None
    assert memory_trim._trim_thread.is_alive()


class _StopConsuming(BaseException):
    """Not an Exception, so run()'s start-over loop does not catch it."""


def test_graph_message_consumer_starts_the_trim_thread(fake_libc, monkeypatch):
    consumer = GraphMessageStreamConsumer(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        store=None,
        consumer_name="trim-test",
        batch_size=1,
    )
    trim_thread_when_consuming = []

    def record_and_stop():
        trim_thread_when_consuming.append(memory_trim._trim_thread)
        raise _StopConsuming

    # run() never returns on its own; stop it once it starts consuming.
    monkeypatch.setattr(consumer, "start", record_and_stop)

    with pytest.raises(_StopConsuming):
        consumer.run()

    assert trim_thread_when_consuming[0] is not None
    assert trim_thread_when_consuming[0].is_alive()
