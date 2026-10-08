"""Session SSE through nginx: live stream of a run, replay after the end, and refusals.

The live run uses its own flow whose python code sleeps, so the gap between the python
node's `start` and `finish` messages is known whatever the sandbox venv state (a cold venv
adds ~33 s, a warm one ~1 s). Buffering anywhere on the way would deliver both at once.
The server never closes the stream; the collector closes it.
"""

import functools

import httpx
import pytest

from helpers.api import ApiClient, assert_error
from helpers.bootstrap import unique_suffix
from helpers.flows import (
    CreatedFlow,
    create_flow,
    runtime_node_name,
    start_session,
    wait_for_graph_end,
)
from helpers.payloads import python_flow_save_payload
from helpers.polling import session_diagnostics
from helpers.sse import SessionStream, collect_session_stream, issue_sse_ticket
from helpers.timings import Timings

PYTHON_SLEEP_SECONDS = 6
SLEEPING_SUM_CODE = (
    "import time\n"
    "def main(a, b):\n"
    f"    time.sleep({PYTHON_SLEEP_SECONDS})\n"
    '    return {"sum": a + b}'
)
# Below the sleep, so scheduling jitter cannot fail an unbuffered stream.
MINIMUM_START_TO_FINISH_SECONDS = PYTHON_SLEEP_SECONDS - 1
FIRST_EVENT_LIMIT_SECONDS = 5
# Covers a cold venv build (~33 s) plus the sleep with no events in between.
LIVE_READ_TIMEOUT_SECONDS = 90
LIVE_DEADLINE_SECONDS = 180
REPLAY_READ_TIMEOUT_SECONDS = 15
REPLAY_DEADLINE_SECONDS = 30
MESSAGES_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def sse_flow(user_client: ApiClient) -> CreatedFlow:
    build_payload = functools.partial(python_flow_save_payload, code=SLEEPING_SUM_CODE)
    return create_flow(user_client, f"e2e-sse-{unique_suffix()}", build_payload)


@pytest.fixture(scope="module")
def live_stream(
    user_client: ApiClient, sse_flow: CreatedFlow, timings: Timings
) -> tuple[int, SessionStream]:
    # Ticket first (30 s TTL, consumed at once), then start the run and subscribe right away.
    # The endpoint subscribes to Redis before replaying, so nothing between the two is lost.
    ticket = issue_sse_ticket(user_client)["ticket"]
    session_id = start_session(user_client, sse_flow.graph_id, {"a": 2, "b": 3})["session_id"]
    stream = collect_session_stream(
        user_client,
        session_id,
        ticket,
        read_timeout=LIVE_READ_TIMEOUT_SECONDS,
        deadline_seconds=LIVE_DEADLINE_SECONDS,
    )
    if stream.first_event_after_seconds is not None:
        timings.record("sse_first_event_seconds", stream.first_event_after_seconds)
    return session_id, stream


@pytest.fixture(scope="module")
def replay(user_client: ApiClient, live_stream: tuple[int, SessionStream]) -> SessionStream:
    session_id, _ = live_stream
    return collect_session_stream(
        user_client,
        session_id,
        issue_sse_ticket(user_client)["ticket"],
        read_timeout=REPLAY_READ_TIMEOUT_SECONDS,
        deadline_seconds=REPLAY_DEADLINE_SECONDS,
    )


def python_node_name(flow: CreatedFlow) -> str:
    [python_node] = flow.saved["python_node_list"]
    return runtime_node_name(python_node)


def test_ticket_is_short_lived(user_client: ApiClient) -> None:
    body = issue_sse_ticket(user_client)
    assert body["ticket"]
    assert body["expires_in"] == 30


def test_live_stream_is_an_event_stream(live_stream: tuple[int, SessionStream]) -> None:
    _, stream = live_stream
    assert stream.content_type.startswith("text/event-stream"), stream.summary()


def test_live_stream_reaches_end(
    user_client: ApiClient, live_stream: tuple[int, SessionStream]
) -> None:
    session_id, stream = live_stream
    assert stream.final_status == "end", (
        f"{stream.summary()}\n{session_diagnostics(user_client, session_id)}"
    )


def test_live_stream_carries_the_run_messages(
    sse_flow: CreatedFlow, live_stream: tuple[int, SessionStream]
) -> None:
    _, stream = live_stream
    python_types = stream.message_types(python_node_name(sse_flow))
    assert "start" in python_types and "finish" in python_types, stream.summary()
    assert stream.has_graph_end(), stream.summary()


def test_first_event_arrives_promptly(live_stream: tuple[int, SessionStream]) -> None:
    _, stream = live_stream
    assert stream.first_event_after_seconds is not None, stream.summary()
    assert stream.first_event_after_seconds < FIRST_EVENT_LIMIT_SECONDS, stream.summary()


def test_live_events_are_not_buffered(
    sse_flow: CreatedFlow, live_stream: tuple[int, SessionStream]
) -> None:
    """The python node's `start` must reach the client well before its `finish`."""
    _, stream = live_stream
    name = python_node_name(sse_flow)
    started = stream.arrival_of(name, "start")
    finished = stream.arrival_of(name, "finish")
    assert started is not None and finished is not None, stream.summary()
    assert finished - started >= MINIMUM_START_TO_FINISH_SECONDS, (
        f"start at {started:.2f}s, finish at {finished:.2f}s: the stream was buffered "
        f"({stream.summary()})"
    )


def test_replay_after_end_has_every_message(
    user_client: ApiClient, live_stream: tuple[int, SessionStream], replay: SessionStream
) -> None:
    session_id, _ = live_stream
    assert replay.final_status == "end", replay.summary()
    stored = wait_for_graph_end(user_client, session_id, MESSAGES_TIMEOUT_SECONDS)
    assert set(replay.messages) == {str(message["uuid"]) for message in stored}, replay.summary()


def test_consumed_ticket_is_rejected(
    user_client: ApiClient, live_stream: tuple[int, SessionStream]
) -> None:
    session_id, _ = live_stream
    ticket = issue_sse_ticket(user_client)["ticket"]
    # Consume it with a short subscription to the ended session (replay only).
    collect_session_stream(
        user_client,
        session_id,
        ticket,
        read_timeout=REPLAY_READ_TIMEOUT_SECONDS,
        deadline_seconds=REPLAY_DEADLINE_SECONDS,
    )
    response = user_client.get(
        f"/api/run-session/subscribe/{session_id}/", params={"ticket": ticket}, expect=None
    )
    assert_error(response, 401, "invalid_sse_ticket")


def test_missing_ticket_is_rejected(
    user_client: ApiClient, live_stream: tuple[int, SessionStream]
) -> None:
    session_id, _ = live_stream
    response = user_client.get(f"/api/run-session/subscribe/{session_id}/", expect=None)
    assert_error(response, 401, "invalid_sse_ticket")


def test_session_of_another_org_is_not_found(
    user_client: ApiClient, other_org_session_id: int
) -> None:
    ticket = issue_sse_ticket(user_client)["ticket"]
    # Streamed so that a wrongly granted stream would not hang the test.
    with user_client.stream(
        "GET",
        f"/api/run-session/subscribe/{other_org_session_id}/",
        params={"ticket": ticket},
        timeout=httpx.Timeout(10, read=10),
        expect=None,
    ) as response:
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            pytest.fail(f"another org's session was streamed (status {response.status_code})")
        response.read()
    assert_error(response, 404, "session_not_found")
