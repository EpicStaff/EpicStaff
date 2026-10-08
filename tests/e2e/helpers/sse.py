"""Session SSE stream: ticket, frame parser and a collector that knows when to stop.

`GET /api/run-session/subscribe/<session_id>/?ticket=...` subscribes to Redis first, then
replays the session (cached and stored messages, current status), then streams live
`messages` / `status` events. The server never closes the stream and sends no heartbeat
while it waits, so the collector closes it itself: once the session is terminal (and, for
`end`, once `graph_end` arrived), or when a hard deadline passes.

`messages` data comes in two shapes: the live Redis payload and a stored database row. Both
carry `uuid`, `name` and `message_data`; the collector keys messages by `uuid`.
"""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

from helpers.api import ApiClient
from helpers.polling import TERMINAL_SESSION_STATUSES
from helpers.redaction import register_secret

SSE_CONNECT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class SseEvent:
    event: str
    data: object
    received_after_seconds: float


@dataclass
class SessionStream:
    """Everything one subscription received, in arrival order."""

    content_type: str = ""
    events: list[SseEvent] = field(default_factory=list)
    messages: dict[str, dict] = field(default_factory=dict)
    statuses: list[str] = field(default_factory=list)
    terminal_status_after_seconds: float | None = None

    @property
    def first_event_after_seconds(self) -> float | None:
        return self.events[0].received_after_seconds if self.events else None

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
    """Subscribe and collect until the session is done or `deadline_seconds` pass.

    `read_timeout` bounds the silence between two reads; the stream has no heartbeat, so it
    must exceed the longest quiet stretch of the run. Returns what arrived either way; the
    caller asserts on completeness.
    """
    stream = SessionStream()
    started = time.monotonic()
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
                if stream_is_done(stream) or time.monotonic() - started > deadline_seconds:
                    break
        except httpx.ReadTimeout:
            # Silence longer than read_timeout: return what arrived; assertions explain.
            pass
    return stream


def record_event(stream: SessionStream, event: SseEvent) -> None:
    stream.events.append(event)
    if event.event == "messages" and isinstance(event.data, dict):
        stream.messages.setdefault(str(event.data["uuid"]), event.data)
    elif event.event == "status" and isinstance(event.data, dict):
        stream.statuses.append(event.data["status"])
        if (
            event.data["status"] in TERMINAL_SESSION_STATUSES
            and stream.terminal_status_after_seconds is None
        ):
            stream.terminal_status_after_seconds = event.received_after_seconds
