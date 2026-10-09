import itertools

import fakeredis
import pytest
from django.conf import settings
from loguru import logger

from tables.services import redis_pubsub


@pytest.fixture
def pubsub(monkeypatch):
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub,
        "_create_redis_client",
        lambda self: fakeredis.FakeRedis(decode_responses=True),
    )
    yield redis_pubsub.RedisPubSub()


@pytest.fixture
def handler_duration(monkeypatch):
    """Make every handler appear to run for the seconds set on the returned dict."""
    duration = {"seconds": 0.0}
    calls = itertools.count()

    def monotonic():
        # Each timed call reads the clock twice: when the handler starts, when it ends.
        return 0.0 if next(calls) % 2 == 0 else duration["seconds"]

    monkeypatch.setattr(redis_pubsub.time, "monotonic", monotonic)
    yield duration


@pytest.fixture
def logged():
    messages = []
    handler_id = logger.add(
        lambda message: messages.append((message.record["level"].name, message.record["message"])),
        level="INFO",
    )
    yield messages
    logger.remove(handler_id)


def _timing_logs(logged):
    return [(level, text) for level, text in logged if " took " in text]


def test_slow_handler_is_logged_as_a_warning(pubsub, handler_duration, logged):
    handler_duration["seconds"] = redis_pubsub.SLOW_HANDLER_SECONDS + 0.5
    pubsub.set_handler("some-channel", lambda message: None)

    pubsub.handlers["some-channel"]({"data": "{}"})

    assert _timing_logs(logged) == [
        ("WARNING", "Handler for some-channel took 1500 ms; the messages behind it waited")
    ]


def test_fast_handler_logs_nothing_unless_every_duration_is_asked_for(
    pubsub, handler_duration, logged
):
    handler_duration["seconds"] = 0.25
    pubsub.set_handler("quiet-channel", lambda message: None)
    pubsub.set_handler("trigger-channel", lambda message: None, log_every_duration=True)

    pubsub.handlers["quiet-channel"]({"data": "{}"})
    pubsub.handlers["trigger-channel"]({"data": "{}"})

    assert _timing_logs(logged) == [("INFO", "Handler for trigger-channel took 250 ms")]


def test_pattern_handler_is_timed_under_its_pattern(pubsub, handler_duration, logged):
    handler_duration["seconds"] = redis_pubsub.SLOW_HANDLER_SECONDS
    pubsub.set_pattern_handler("session:update:*:status", lambda message: None)

    pubsub.pattern_handlers["session:update:*:status"]({"data": "{}"})

    assert _timing_logs(logged) == [
        (
            "WARNING",
            "Handler for session:update:*:status took 1000 ms; the messages behind it waited",
        )
    ]


def test_failing_handler_is_still_timed_and_its_error_propagates(
    pubsub, handler_duration, logged
):
    handler_duration["seconds"] = redis_pubsub.SLOW_HANDLER_SECONDS + 1

    def failing_handler(message):
        raise RuntimeError("boom")

    pubsub.set_handler("failing-channel", failing_handler)

    with pytest.raises(RuntimeError, match="boom"):
        pubsub.handlers["failing-channel"]({"data": "{}"})
    assert [level for level, _text in _timing_logs(logged)] == ["WARNING"]


def test_worker_logs_the_duration_of_every_trigger_message(
    monkeypatch, pubsub, handler_duration, logged
):
    monkeypatch.setattr(redis_pubsub, "start_periodic_malloc_trim", lambda: None)
    # The worker registers its handlers, then loops forever; stop it after registration.
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_run_with_reconnect", lambda self, label, inner_loop: None
    )
    pubsub.listen_for_redis_messages_worker()
    handler_duration["seconds"] = 0.1

    # Malformed on purpose: each handler returns before touching the database.
    pubsub.handlers[settings.WEBHOOK_MESSAGE_CHANNEL]({"data": "not json"})
    pubsub.handlers[settings.SCHEDULE_CHANNEL]({"data": "not json"})
    pubsub.handlers[settings.CODE_RESULT_CHANNEL]({"data": "not json"})

    assert _timing_logs(logged) == [
        ("INFO", f"Handler for {settings.WEBHOOK_MESSAGE_CHANNEL} took 100 ms"),
        ("INFO", f"Handler for {settings.SCHEDULE_CHANNEL} took 100 ms"),
    ]
