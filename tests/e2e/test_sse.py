"""Session SSE through nginx: live stream of a flow A run, replay after the end, and refusals.

Flow A pays the sandbox venv rebuild (~33 s, no events in between), so the read timeout
covers that silence. The stream never closes by itself; the collector closes it.
"""

import httpx
import pytest

from helpers.api import ApiClient, assert_error
from helpers.bootstrap import unique_suffix
from helpers.flows import (
    CreatedFlow,
    create_python_flow,
    runtime_node_name,
    start_session,
    wait_for_graph_end,
)
from helpers.polling import TERMINAL_SESSION_STATUSES, session_diagnostics
from helpers.sse import SessionStream, collect_session_stream, issue_sse_ticket
from helpers.timings import Timings

LIVE_READ_TIMEOUT_SECONDS = 90
LIVE_DEADLINE_SECONDS = 180
REPLAY_READ_TIMEOUT_SECONDS = 15
REPLAY_DEADLINE_SECONDS = 30
MESSAGES_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def sse_flow(user_client: ApiClient) -> CreatedFlow:
    return create_python_flow(user_client, f"e2e-sse-{unique_suffix()}")


@pytest.fixture(scope="module")
def live_stream(user_client: ApiClient, sse_flow: CreatedFlow, timings: Timings) -> tuple[int, SessionStream]:
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
def replay(user_client: ApiClient, live_stream: tuple[int, SessionStream]) -> tuple[str, SessionStream]:
    session_id, _ = live_stream
    ticket = issue_sse_ticket(user_client)["ticket"]
    stream = collect_session_stream(
        user_client,
        session_id,
        ticket,
        read_timeout=REPLAY_READ_TIMEOUT_SECONDS,
        deadline_seconds=REPLAY_DEADLINE_SECONDS,
    )
    return ticket, stream


def python_node_name(flow: CreatedFlow) -> str:
    [python_node] = flow.saved["python_node_list"]
    return runtime_node_name(python_node)


def test_ticket_is_short_lived(user_client: ApiClient) -> None:
    body = issue_sse_ticket(user_client)
    assert body["ticket"]
    assert body["expires_in"] == 30


def test_live_stream_is_an_event_stream(live_stream: tuple[int, SessionStream]) -> None:
    _, stream = live_stream
    assert stream.content_type.startswith("text/event-stream"), stream.content_type


def test_live_stream_reaches_end(
    user_client: ApiClient, live_stream: tuple[int, SessionStream]
) -> None:
    session_id, stream = live_stream
    assert stream.final_status == "end", (
        f"statuses seen: {stream.statuses}\n{session_diagnostics(user_client, session_id)}"
    )


def test_live_stream_carries_the_run_messages(
    sse_flow: CreatedFlow, live_stream: tuple[int, SessionStream]
) -> None:
    _, stream = live_stream
    python_types = stream.message_types(python_node_name(sse_flow))
    assert "start" in python_types and "finish" in python_types, python_types
    assert stream.has_graph_end(), stream.message_types()


def test_live_events_arrive_before_the_session_ends(live_stream: tuple[int, SessionStream]) -> None:
    """Proves no buffering on the way: events reach the client while the run is still going."""
    _, stream = live_stream
    assert stream.terminal_status_after_seconds is not None, stream.statuses
    assert stream.first_event_after_seconds < stream.terminal_status_after_seconds
    terminal_index = next(
        index for index, status in enumerate(stream.statuses) if status in TERMINAL_SESSION_STATUSES
    )
    assert terminal_index > 0, f"no non-terminal status arrived before {stream.statuses}"


def test_replay_after_end_has_every_message(
    user_client: ApiClient, live_stream: tuple[int, SessionStream], replay: tuple[str, SessionStream]
) -> None:
    session_id, _ = live_stream
    _, stream = replay
    assert stream.final_status == "end", stream.statuses
    stored = wait_for_graph_end(user_client, session_id, MESSAGES_TIMEOUT_SECONDS)
    assert set(stream.messages) == {str(message["uuid"]) for message in stored}


def test_consumed_ticket_is_rejected(
    user_client: ApiClient, live_stream: tuple[int, SessionStream], replay: tuple[str, SessionStream]
) -> None:
    session_id, _ = live_stream
    used_ticket, _ = replay
    response = user_client.get(
        f"/api/run-session/subscribe/{session_id}/", params={"ticket": used_ticket}, expect=None
    )
    assert_error(response, 401, "invalid_sse_ticket")


def test_missing_ticket_is_rejected(user_client: ApiClient, live_stream: tuple[int, SessionStream]) -> None:
    session_id, _ = live_stream
    response = user_client.get(f"/api/run-session/subscribe/{session_id}/", expect=None)
    assert_error(response, 401, "invalid_sse_ticket")


def test_session_of_another_org_is_not_found(user_client: ApiClient, other_org_session_id: int) -> None:
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
