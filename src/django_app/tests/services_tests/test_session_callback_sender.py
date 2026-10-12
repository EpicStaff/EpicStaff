import json
import threading
import uuid
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
from django.db import connection
from django.utils import timezone

from tables.models import GraphSessionMessage, SessionCallback
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from tables.services.session_callbacks.sender import (
    BATCH_SIZE,
    MAX_RESULT_WAIT_ATTEMPTS,
    RESULT_WAIT,
    RETRY_DELAYS,
    SessionCallbackSender,
)
from tables.services.session_callbacks.signing import (
    SESSION_ID_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign,
)
from tests.fixtures import *

SECRET = "s" * 32


def _pending(session, status="end", end_node_result="done"):
    now = timezone.now()
    return SessionCallback.objects.create(
        session=session,
        url="http://chat:8000/cb",
        secret=SECRET,
        status=SessionCallback.Status.PENDING,
        next_attempt_at=now,
        payload={
            "session_id": session.pk,
            "graph_id": session.graph_id,
            "status": status,
            "end_node_result": end_node_result,
            "token_usage": {"total_tokens": 1},
            "finished_at": now.isoformat(),
        },
    )


class Recorder:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.requests = []

    def transport(self):
        def handle(request):
            self.requests.append(request)
            return httpx.Response(self.status_code)

        return httpx.MockTransport(handle)


@pytest.mark.django_db
def test_delivers_signed_payload_and_clears_secret(session):
    callback = _pending(session)
    recorder = Recorder(200)
    now = timezone.now()

    attempted = SessionCallbackSender(transport=recorder.transport()).send_due(now)

    callback.refresh_from_db()
    assert attempted == 1
    assert callback.status == SessionCallback.Status.DELIVERED
    assert callback.secret == ""
    request = recorder.requests[0]
    body = request.content.decode()
    assert request.url == "http://chat:8000/cb"
    assert request.headers["content-type"] == "application/json"
    assert request.headers[SESSION_ID_HEADER] == str(session.pk)
    timestamp = request.headers[TIMESTAMP_HEADER]
    assert request.headers[SIGNATURE_HEADER] == sign(SECRET, timestamp, body)
    assert json.loads(body)["end_node_result"] == "done"


@pytest.mark.django_db
def test_failure_schedules_first_retry(session):
    callback = _pending(session)
    now = timezone.now()

    SessionCallbackSender(transport=Recorder(500).transport()).send_due(now)

    callback.refresh_from_db()
    assert callback.status == SessionCallback.Status.PENDING
    assert callback.attempts == 1
    assert now + RETRY_DELAYS[0] <= callback.next_attempt_at <= timezone.now() + RETRY_DELAYS[0]
    assert "500" in callback.last_error
    assert callback.secret == SECRET


@pytest.mark.django_db
def test_connection_error_is_recorded_and_retried(session):
    callback = _pending(session)
    now = timezone.now()

    def boom(request):
        raise httpx.ConnectError("refused")

    SessionCallbackSender(transport=httpx.MockTransport(boom)).send_due(now)

    callback.refresh_from_db()
    assert callback.status == SessionCallback.Status.PENDING
    assert callback.attempts == 1
    assert "refused" in callback.last_error


@pytest.mark.django_db
def test_last_retry_marks_failed(session):
    callback = _pending(session)
    callback.attempts = len(RETRY_DELAYS)
    callback.save()
    now = timezone.now()

    SessionCallbackSender(transport=Recorder(503).transport()).send_due(now)

    callback.refresh_from_db()
    assert callback.status == SessionCallback.Status.FAILED
    assert callback.attempts == len(RETRY_DELAYS) + 1


@pytest.mark.django_db
def test_not_due_rows_are_skipped(session):
    callback = _pending(session)
    callback.next_attempt_at = timezone.now() + timedelta(minutes=5)
    callback.save()
    recorder = Recorder(200)

    attempted = SessionCallbackSender(transport=recorder.transport()).send_due(timezone.now())

    assert attempted == 0
    assert recorder.requests == []


@pytest.mark.django_db
def test_end_without_result_waits_then_sends_null(session):
    callback = _pending(session, status="end", end_node_result=None)
    recorder = Recorder(200)
    sender = SessionCallbackSender(transport=recorder.transport())
    now = timezone.now()

    # `_attempt` stamps real time, so selection looks ahead instead of faking the clock.
    later = now + timedelta(hours=1)
    for attempt in range(MAX_RESULT_WAIT_ATTEMPTS):
        sender.send_due(later)
        callback.refresh_from_db()
        assert recorder.requests == [], f"sent too early on wait {attempt}"
        assert callback.status == SessionCallback.Status.PENDING
        assert now + RESULT_WAIT <= callback.next_attempt_at <= timezone.now() + RESULT_WAIT

    sender.send_due(later)

    callback.refresh_from_db()
    assert callback.status == SessionCallback.Status.DELIVERED
    assert json.loads(recorder.requests[0].content)["end_node_result"] is None


@pytest.mark.django_db
def test_end_without_result_picks_up_late_graph_end(session):
    callback = _pending(session, status="end", end_node_result=None)
    recorder = Recorder(200)
    sender = SessionCallbackSender(transport=recorder.transport())
    now = timezone.now()

    sender.send_due(now)
    GraphSessionMessage.objects.create(
        session=session,
        created_at=now,
        name="__end_node__",
        execution_order=1,
        message_data={"message_type": "graph_end", "end_node_result": {"reply": "late"}},
        uuid=uuid.uuid4(),
    )
    sender.send_due(now + timedelta(hours=1))

    callback.refresh_from_db()
    assert callback.status == SessionCallback.Status.DELIVERED
    assert json.loads(recorder.requests[0].content)["end_node_result"] == {"reply": "late"}


# Transactional: the transport runs in a pool thread with its own connection, which
# cannot see rows from an uncommitted test transaction.
@pytest.mark.django_db(transaction=True)
def test_row_deleted_mid_send_does_not_crash(session):
    callback = _pending(session)

    def delete_then_ok(request):
        try:
            SessionCallback.objects.filter(pk=callback.pk).delete()
        finally:
            connection.close()
        return httpx.Response(200)

    attempted = SessionCallbackSender(transport=httpx.MockTransport(delete_then_ok)).send_due(timezone.now())

    assert attempted == 1
    assert not SessionCallback.objects.filter(pk=callback.pk).exists()


@pytest.mark.django_db
def test_crashing_row_is_recorded_and_next_row_still_sent(session, session_data):
    bad = _pending(session)
    SessionCallback.objects.filter(pk=bad.pk).update(url="http://chat:abc/cb")
    other = SessionManagerService().create_session(**session_data, trigger=TriggerSpec.manual())
    good = _pending(other)
    recorder = Recorder(200)
    now = timezone.now()

    attempted = SessionCallbackSender(transport=recorder.transport()).send_due(now)

    bad.refresh_from_db()
    good.refresh_from_db()
    assert attempted == 2
    assert bad.attempts == 1
    assert bad.status == SessionCallback.Status.PENDING
    assert bad.next_attempt_at > timezone.now()
    assert good.status == SessionCallback.Status.DELIVERED


def _other_session(session_data):
    return SessionManagerService().create_session(**session_data, trigger=TriggerSpec.manual())


@pytest.mark.django_db
def test_rows_of_one_batch_are_sent_concurrently(session, session_data):
    callbacks = [_pending(session)] + [_pending(_other_session(session_data)) for _ in range(2)]
    # Serial sending never fills the barrier: it breaks after the timeout and the rows fail.
    in_flight = threading.Barrier(len(callbacks), timeout=5)

    def wait_for_all(request):
        in_flight.wait()
        return httpx.Response(200)

    attempted = SessionCallbackSender(transport=httpx.MockTransport(wait_for_all)).send_due(
        timezone.now()
    )

    assert attempted == len(callbacks)
    for callback in callbacks:
        callback.refresh_from_db()
        assert callback.status == SessionCallback.Status.DELIVERED, callback.last_error


@pytest.mark.django_db
def test_crash_inside_send_still_records_the_other_rows(session, session_data):
    bad = _pending(session)
    SessionCallback.objects.filter(pk=bad.pk).update(url="http://chat:8000/crash")
    good = [_pending(_other_session(session_data)) for _ in range(2)]

    def crash_one(request):
        if request.url.path == "/crash":
            raise RuntimeError("transport bug")
        return httpx.Response(200)

    attempted = SessionCallbackSender(transport=httpx.MockTransport(crash_one)).send_due(
        timezone.now()
    )

    bad.refresh_from_db()
    assert attempted == 3
    assert bad.status == SessionCallback.Status.PENDING
    assert bad.attempts == 1
    assert "RuntimeError: transport bug" in bad.last_error
    for callback in good:
        callback.refresh_from_db()
        assert callback.status == SessionCallback.Status.DELIVERED


@pytest.mark.django_db
def test_row_waiting_for_result_does_not_block_the_others(session, session_data):
    waiting = _pending(session, status="end", end_node_result=None)
    ready = _pending(_other_session(session_data))
    recorder = Recorder(200)
    now = timezone.now()

    attempted = SessionCallbackSender(transport=recorder.transport()).send_due(now)

    waiting.refresh_from_db()
    ready.refresh_from_db()
    assert attempted == 2
    assert ready.status == SessionCallback.Status.DELIVERED
    assert waiting.status == SessionCallback.Status.PENDING
    assert waiting.attempts == 0
    assert waiting.next_attempt_at >= now + RESULT_WAIT
    assert [request.headers[SESSION_ID_HEADER] for request in recorder.requests] == [
        str(ready.session_id)
    ]


class _StopLoop(BaseException):
    """Not an `Exception`, so the loop's own error handler cannot swallow it."""


def _run_passes(pass_results):
    """Run `run_forever` over `pass_results` (counts or exceptions); return the sleep mock."""
    sender = SessionCallbackSender(transport=Recorder().transport())
    # The pass after the scripted ones stops the loop.
    with (
        patch.object(sender, "send_due", side_effect=[*pass_results, _StopLoop()]),
        patch("tables.services.session_callbacks.sender.close_old_connections"),
        patch("tables.services.session_callbacks.sender.time.sleep") as sleep,
    ):
        try:
            sender.run_forever(interval_seconds=1.0)
        except _StopLoop:
            pass
    return sleep


def test_run_forever_skips_sleep_after_full_batch():
    sleep = _run_passes([BATCH_SIZE, BATCH_SIZE])

    sleep.assert_not_called()


def test_run_forever_sleeps_after_partial_batch():
    sleep = _run_passes([BATCH_SIZE, BATCH_SIZE - 1, 0])

    assert sleep.call_count == 2
    sleep.assert_called_with(1.0)


def test_run_forever_sleeps_after_failed_pass():
    sleep = _run_passes([RuntimeError("db down")])

    sleep.assert_called_once_with(1.0)
