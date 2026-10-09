"""Session SSE through nginx: runtime delivery of a flow B run, replay of a flow A run, refusals.

Runtime delivery is proven with the stream's replay/live boundary (see helpers/sse.py): on
connect the server replays what exists, then sends one `status` read from the database,
then forwards live Redis events. If the run is still going at that boundary, the nodes'
`finish` messages, `graph_end` and the `end` status can only reach the client through the
live path, which crew feeds as each node finishes.

The live run is flow B (Start -> Knowledge -> Task with the agent -> End, no sandbox). The
ticket is issued before the run starts and the stream is opened right after the run-session
POST, but subscribing needs the session id the POST returns, so the run's earliest asserted
event (the knowledge node's `finish`) can precede the subscription. That is a harness race
and the only retried case ("too late", see `subscribed_too_late`): it is detected as soon
as the boundary status arrives, and a fresh run and ticket are used, at most LIVE_ATTEMPTS
times in all. Every other problem (an error status, missing live events, wrong order,
timeouts) fails on the first attempt. Replay and ticket checks use an ended flow A run.
"""

import functools
import logging
import time
import warnings
from dataclasses import dataclass

import httpx
import pytest

from fixtures.knowledge import IndexedRag
from helpers.api import ApiClient, assert_error
from helpers.bootstrap import unique_suffix
from helpers.flows import (
    CreatedFlow,
    FlowRun,
    assert_session_ended,
    create_flow,
    create_python_flow,
    run_flow_and_wait,
    runtime_name_of,
    start_session,
    wait_for_graph_end,
)
from helpers.payloads import agent_rag_flow_save_payload
from helpers.polling import TERMINAL_SESSION_STATUSES, session_diagnostics
from helpers.sse import (
    LIVE_PHASE,
    REPLAY_PHASE,
    SessionStream,
    collect_session_stream,
    issue_sse_ticket,
)
from helpers.timings import Timings

logger = logging.getLogger("e2e.sse")

FIRST_EVENT_LIMIT_SECONDS = 5
# Fresh runs allowed when the subscription arrives after the knowledge node already finished.
LIVE_ATTEMPTS = 3
# Flow B has no sandbox step; the longest quiet stretch is one agent turn on the mock LLM.
LIVE_READ_TIMEOUT_SECONDS = 60
LIVE_DEADLINE_SECONDS = 120
REPLAY_READ_TIMEOUT_SECONDS = 15
REPLAY_DEADLINE_SECONDS = 30
# Flow A for the replay: covers a cold venv build (~33 s).
REPLAY_RUN_TIMEOUT_SECONDS = 180
MESSAGES_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class LiveRun:
    session_id: int
    stream: SessionStream
    # time.monotonic() just before the run-session POST.
    posted_at: float
    attempts: int

    def seconds_after_post(self, event_index: int | None) -> float | None:
        if event_index is None:
            return None
        event = self.stream.events[event_index]
        return self.stream.connected_at - self.posted_at + event.received_after_seconds


@pytest.fixture(scope="module")
def live_flow(
    user_client: ApiClient,
    rag_collection: dict,
    naive_rag: dict,
    indexed_rag: IndexedRag,
    knowledge_surface: dict,
    e2e_agent: dict,
) -> CreatedFlow:
    build_payload = functools.partial(
        agent_rag_flow_save_payload,
        collection_id=rag_collection["collection_id"],
        naive_rag_id=naive_rag["naive_rag"]["naive_rag_id"],
        agent_definition_id=e2e_agent["id"],
        surface_id=knowledge_surface["id"],
    )
    return create_flow(user_client, f"e2e-sse-live-{unique_suffix()}", build_payload)


@pytest.fixture(scope="module")
def live_run(user_client: ApiClient, live_flow: CreatedFlow, timings: Timings) -> LiveRun:
    knowledge_name = runtime_name_of(live_flow, "knowledge_node_list")
    for attempt in range(1, LIVE_ATTEMPTS + 1):
        run = subscribe_to_a_fresh_run(user_client, live_flow, attempt, knowledge_name)
        # Any other outcome, an `error` status included, fails the tests below instead.
        if not subscribed_too_late(run.stream, knowledge_name):
            break
        logger.info(
            "SSE attempt %s: subscribed too late to session %s (initial status %r)",
            attempt,
            run.session_id,
            run.stream.initial_status,
        )
    timings.record("sse_live_attempts", run.attempts)
    if run.attempts > 1:
        warnings.warn(
            f"live SSE check needed {run.attempts} attempts: subscribed too late", stacklevel=1
        )
    stream = run.stream
    if stream.first_event_after_seconds is not None:
        timings.record("sse_first_event_seconds", stream.first_event_after_seconds)
    initial_status_after_post = run.seconds_after_post(stream.boundary_index)
    end_after_post = run.seconds_after_post(stream.status_index("end"))
    if initial_status_after_post is not None:
        timings.record("sse_post_to_initial_status_seconds", initial_status_after_post)
    if end_after_post is not None:
        timings.record("sse_post_to_end_seconds", end_after_post)
    return run


def subscribed_too_late(stream: SessionStream, knowledge_name: str) -> bool:
    """The run ended already, or its knowledge `finish` (earliest asserted event) was replayed."""
    if stream.initial_status == "end":
        return True
    if stream.initial_status in TERMINAL_SESSION_STATUSES:
        return False
    return stream.phase_at(stream.message_index("finish", knowledge_name)) == REPLAY_PHASE


def subscribe_to_a_fresh_run(
    user_client: ApiClient, flow: CreatedFlow, attempt: int, knowledge_name: str
) -> LiveRun:
    # Ticket first (30 s TTL, consumed at once), then start the run and subscribe right away.
    ticket = issue_sse_ticket(user_client)["ticket"]
    posted_at = time.monotonic()
    session_id = start_session(user_client, flow.graph_id, {})["session_id"]
    stream = collect_session_stream(
        user_client,
        session_id,
        ticket,
        read_timeout=LIVE_READ_TIMEOUT_SECONDS,
        deadline_seconds=LIVE_DEADLINE_SECONDS,
        stop_at_boundary=lambda replayed: subscribed_too_late(replayed, knowledge_name),
    )
    return LiveRun(session_id, stream, posted_at, attempt)


@pytest.fixture(scope="module")
def ended_run(user_client: ApiClient) -> FlowRun:
    """A finished flow A run, for replay and ticket checks."""
    flow = create_python_flow(user_client, f"e2e-sse-replay-{unique_suffix()}")
    run = run_flow_and_wait(user_client, flow.graph_id, {"a": 2, "b": 3}, REPLAY_RUN_TIMEOUT_SECONDS)
    assert_session_ended(user_client, run.session_id, run.status)
    return run


@pytest.fixture(scope="module")
def replay(user_client: ApiClient, ended_run: FlowRun) -> SessionStream:
    return collect_session_stream(
        user_client,
        ended_run.session_id,
        issue_sse_ticket(user_client)["ticket"],
        read_timeout=REPLAY_READ_TIMEOUT_SECONDS,
        deadline_seconds=REPLAY_DEADLINE_SECONDS,
    )


def delivery_indexes(flow: CreatedFlow, stream: SessionStream) -> dict[str, int | None]:
    return {
        "knowledge finish": stream.message_index("finish", runtime_name_of(flow, "knowledge_node_list")),
        "task finish": stream.message_index("finish", runtime_name_of(flow, "task_node_list")),
        "graph_end": stream.message_index("graph_end"),
        "status end": stream.status_index("end"),
    }


def test_ticket_is_short_lived(user_client: ApiClient) -> None:
    body = issue_sse_ticket(user_client)
    assert body["ticket"]
    assert body["expires_in"] == 30


def test_live_stream_is_an_event_stream(live_run: LiveRun) -> None:
    assert live_run.stream.content_type.startswith("text/event-stream"), live_run.stream.summary()


def test_first_event_arrives_promptly(live_run: LiveRun) -> None:
    stream = live_run.stream
    assert stream.first_event_after_seconds is not None, stream.summary()
    assert stream.first_event_after_seconds < FIRST_EVENT_LIMIT_SECONDS, stream.summary()


def test_live_stream_reaches_end(user_client: ApiClient, live_run: LiveRun) -> None:
    stream = live_run.stream
    assert stream.final_status == "end", (
        f"{stream.summary()}\n{session_diagnostics(user_client, live_run.session_id)}"
    )


def test_subscription_starts_while_the_run_is_going(
    live_flow: CreatedFlow, live_run: LiveRun
) -> None:
    stream = live_run.stream
    assert stream.initial_status is not None, f"no status event arrived ({stream.summary()})"
    assert stream.initial_status not in TERMINAL_SESSION_STATUSES - {"end"}, (
        f"run already failed at connect time ({stream.summary()})"
    )
    assert not subscribed_too_late(stream, runtime_name_of(live_flow, "knowledge_node_list")), (
        "subscribed too late, run already finished: cannot prove runtime delivery "
        f"(after {live_run.attempts} attempts; {stream.summary()})"
    )


def test_run_completion_is_delivered_live(live_flow: CreatedFlow, live_run: LiveRun) -> None:
    stream = live_run.stream
    indexes = delivery_indexes(live_flow, live_run.stream)
    phases = {name: stream.phase_at(index) for name, index in indexes.items()}
    assert all(phase == LIVE_PHASE for phase in phases.values()), (
        f"phases {phases} ({stream.summary()})"
    )


def test_live_events_arrive_in_run_order(live_flow: CreatedFlow, live_run: LiveRun) -> None:
    """Node finishes arrive in run order and before the run's completion events.

    `graph_end` and the `end` status are not ordered against each other: the status takes one
    Redis hop to the stream (crew -> status channel), messages take two (crew -> Django ->
    update channel), so `end` can arrive before `graph_end`. That is a known product issue.
    """
    stream = live_run.stream
    indexes = delivery_indexes(live_flow, stream)
    assert None not in indexes.values(), f"{indexes} ({stream.summary()})"
    knowledge, task = indexes["knowledge finish"], indexes["task finish"]
    assert knowledge < task, f"{indexes} ({stream.summary()})"
    assert task < indexes["graph_end"], f"{indexes} ({stream.summary()})"


def test_replay_after_end_has_every_message(
    user_client: ApiClient, ended_run: FlowRun, replay: SessionStream
) -> None:
    assert replay.final_status == "end", replay.summary()
    assert replay.statuses_in_phase(REPLAY_PHASE) == ["end"], replay.summary()
    stored = wait_for_graph_end(user_client, ended_run.session_id, MESSAGES_TIMEOUT_SECONDS)
    assert set(replay.messages) == {str(message["uuid"]) for message in stored}, replay.summary()


def test_consumed_ticket_is_rejected(user_client: ApiClient, ended_run: FlowRun) -> None:
    ticket = issue_sse_ticket(user_client)["ticket"]
    # Consume it with a short subscription to the ended session (replay only).
    collect_session_stream(
        user_client,
        ended_run.session_id,
        ticket,
        read_timeout=REPLAY_READ_TIMEOUT_SECONDS,
        deadline_seconds=REPLAY_DEADLINE_SECONDS,
    )
    response = user_client.get(
        f"/api/run-session/subscribe/{ended_run.session_id}/", params={"ticket": ticket}, expect=None
    )
    assert_error(response, 401, "invalid_sse_ticket")


def test_missing_ticket_is_rejected(user_client: ApiClient, ended_run: FlowRun) -> None:
    response = user_client.get(f"/api/run-session/subscribe/{ended_run.session_id}/", expect=None)
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
