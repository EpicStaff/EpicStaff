"""Session SSE stream: ticket, frame parser and a collector that knows when to stop.

`GET /api/run-session/subscribe/<session_id>/?ticket=...` (`RunSessionSSEView`) subscribes
to Redis first, then replays the session: every cached and stored message, then exactly one
`status` event read from the database. After that it streams live `messages` / `status`
events from Redis pubsub. The first `status` event is therefore the boundary: events up to
and including it are the `replay` phase, events after it the `live` phase. (`memory` events
also follow the initial status during replay; the suite does not assert on them.)

The server never closes the stream and sends no heartbeat while it waits, so the collector
closes it itself: once the session is terminal (and, for `end`, once `graph_end` arrived),
on an `event: fatal-error`, or when a hard deadline passes.

`messages` data comes in two shapes: the live Redis payload and a stored database row. Both
carry `uuid`, `name` and `message_data`; the collector keys messages by `uuid` and keeps the
first arrival.
"""

import dataclasses
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

from helpers.api import ApiClient
from helpers.polling import TERMINAL_SESSION_STATUSES
from helpers.redaction import register_secret

SSE_CONNECT_TIMEOUT_SECONDS = 10
FATAL_ERROR_EVENT = "fatal-error"
REPLAY_PHASE = "replay"
LIVE_PHASE = "live"


@dataclass(frozen=True)
class SseEvent:
    event: str
    data: object
    received_after_seconds: float
    phase: str = ""


@dataclass
class SessionStream:
    """Everything one subscription received, in arrival order."""

    # time.monotonic() when the subscription request was sent.
    connected_at: float = 0.0
    content_type: str = ""
    events: list[SseEvent] = field(default_factory=list)
    messages: dict[str, dict] = field(default_factory=dict)
    # Index into `events` of each message's first arrival.
    message_event_index: dict[str, int] = field(default_factory=dict)
    statuses: list[str] = field(default_factory=list)
    # Index into `events` of the first `status` event (the replay/live boundary).
    boundary_index: int | None = None
    fatal_error: object = None
    # Why collection stopped: done, fatal_error, read_timeout or deadline.
    stop_reason: str = ""

    @property
    def first_event_after_seconds(self) -> float | None:
        return self.events[0].received_after_seconds if self.events else None

    @property
    def initial_status(self) -> str | None:
        """The status the replay reported, read from the database at connect time."""
        return None if self.boundary_index is None else self.events[self.boundary_index].data["status"]

    @property
    def final_status(self) -> str | None:
        return self.statuses[-1] if self.statuses else None

    def message_types(self, name: str | None = None) -> list[str]:
        return [
            message["message_data"].get("message_type")
            for message in self.messages.values()
            if name is None or message.get("name") == name
        ]

    def has_graph_end(self) -> bool:
        return "graph_end" in self.message_types()

    def message_index(self, message_type: str, name: str | None = None) -> int | None:
        """Event index of the first message of `message_type` (from node `name`, if given)."""
        for uuid, message in self.messages.items():
            if message["message_data"].get("message_type") == message_type and (
                name is None or message.get("name") == name
            ):
                return self.message_event_index[uuid]
        return None

    def status_index(self, status: str) -> int | None:
        """Event index of the first `status` event carrying `status`."""
        for index, event in enumerate(self.events):
            if event.event == "status" and isinstance(event.data, dict) and event.data.get("status") == status:
                return index
        return None

    def phase_at(self, index: int | None) -> str | None:
        return None if index is None else self.events[index].phase

    def messages_in_phase(self, phase: str) -> list[dict]:
        return [
            message
            for uuid, message in self.messages.items()
            if self.events[self.message_event_index[uuid]].phase == phase
        ]

    def statuses_in_phase(self, phase: str) -> list[str]:
        return [
            event.data["status"]
            for event in self.events
            if event.event == "status" and event.phase == phase and isinstance(event.data, dict)
        ]

    def summary(self) -> str:
        return (
            f"stop_reason={self.stop_reason!r} initial_status={self.initial_status!r} "
            f"statuses={self.statuses} messages={len(self.messages)} "
            f"(live {len(self.messages_in_phase(LIVE_PHASE))}) events={len(self.events)} "
            f"fatal_error={self.fatal_error!r}"
        )


def issue_sse_ticket(client: ApiClient) -> dict:
    """`POST /api/auth/sse-ticket/`; the ticket is registered as a secret before returning."""
    body = client.post("/api/auth/sse-ticket/").json()
    body["ticket"] = register_secret(body["ticket"])
    return body


def parse_sse_lines(lines: Iterator[str], started: float) -> Iterator[SseEvent]:
    """Turn SSE lines into events: `event:` + one or more `data:` lines, blank line ends.

    Comment lines (`: ping`) are ignored; `data` is JSON-decoded when it parses.
    """
    event_name = "message"
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    data: object = json.loads(raw)
                except json.JSONDecodeError:
                    data = raw
                yield SseEvent(event_name, data, time.monotonic() - started)
            event_name, data_lines = "message", []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "event":
            event_name = value
        elif name == "data":
            data_lines.append(value)


def stream_is_done(stream: SessionStream) -> bool:
    status = stream.final_status
    if status not in TERMINAL_SESSION_STATUSES:
        return False
    # An ended session also publishes graph_end; other terminal statuses may not.
    return status != "end" or stream.has_graph_end()


def collect_session_stream(
    client: ApiClient,
    session_id: int,
    ticket: str,
    *,
    read_timeout: float,
    deadline_seconds: float,
) -> SessionStream:
    """Subscribe and collect until the session is done, a fatal error, or `deadline_seconds`.

    `read_timeout` bounds the silence between two reads; the stream has no heartbeat, so it
    must exceed the longest quiet stretch of the run. Returns what arrived either way, with
    `stop_reason` set; the caller asserts on completeness.
    """
    started = time.monotonic()
    stream = SessionStream(connected_at=started)
    timeout = httpx.Timeout(SSE_CONNECT_TIMEOUT_SECONDS, read=read_timeout)
    with client.stream(
        "GET",
        f"/api/run-session/subscribe/{session_id}/",
        params={"ticket": ticket},
        timeout=timeout,
    ) as response:
        stream.content_type = response.headers.get("content-type", "")
        try:
            for event in parse_sse_lines(response.iter_lines(), started):
                record_event(stream, event)
                if event.event == FATAL_ERROR_EVENT:
                    stream.fatal_error = event.data
                    stream.stop_reason = "fatal_error"
                    break
                if stream_is_done(stream):
                    stream.stop_reason = "done"
                    break
                if time.monotonic() - started > deadline_seconds:
                    stream.stop_reason = "deadline"
                    break
        except httpx.ReadTimeout:
            # Silence longer than read_timeout: return what arrived; assertions explain.
            stream.stop_reason = "read_timeout"
    return stream


def record_event(stream: SessionStream, event: SseEvent) -> None:
    index = len(stream.events)
    phase = REPLAY_PHASE if stream.boundary_index is None else LIVE_PHASE
    event = dataclasses.replace(event, phase=phase)
    stream.events.append(event)
    if event.event == "messages" and isinstance(event.data, dict):
        uuid = str(event.data["uuid"])
        if uuid not in stream.messages:
            stream.messages[uuid] = event.data
            stream.message_event_index[uuid] = index
    elif event.event == "status" and isinstance(event.data, dict):
        stream.statuses.append(event.data["status"])
        if stream.boundary_index is None:
            stream.boundary_index = index
