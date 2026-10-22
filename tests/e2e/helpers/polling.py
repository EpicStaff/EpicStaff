"""Polling with diagnostics, and the session helpers built on it."""

import json
import time
from collections.abc import Callable
from typing import TypeVar

from helpers.api import ApiClient, body_excerpt
from helpers.redaction import redact, scrub

Value = TypeVar("Value")

TERMINAL_SESSION_STATUSES = frozenset({"end", "error", "stop", "expired"})
MESSAGES_PAGE_LIMIT = 200
# Cheap reads (get-updates, message list); short so a finished run is noticed at once.
SESSION_POLL_INTERVAL_SECONDS = 0.25
MESSAGES_MAX_PAGES = 10
LAST_VALUE_EXCERPT_LENGTH = 2000


def poll(
    fetch: Callable[[], Value],
    until: Callable[[Value], bool],
    *,
    timeout: float,
    interval: float = 1.0,
    describe: str,
    diagnostics: Callable[[], str] | None = None,
) -> Value:
    """Call `fetch` until `until(value)` holds and return that value.

    Raises:
        AssertionError: On timeout, with `describe`, the last value (redacted) and the
            output of `diagnostics` when given.
    """
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if until(value):
            return value
        if time.monotonic() >= deadline:
            message = (
                f"Timed out after {timeout:.0f}s waiting for {describe}. "
                f"Last value: {scrub(repr(redact(value)))[:LAST_VALUE_EXCERPT_LENGTH]}"
            )
            if diagnostics is not None:
                message += f"\n{scrub(diagnostics())}"
            raise AssertionError(message)
        time.sleep(interval)


def fetch_session_messages(client: ApiClient, session_id: int) -> list[dict]:
    """All messages of a session, page by page (offset-based, not the absolute `next` URL).

    Raises:
        AssertionError: The session has more than MESSAGES_MAX_PAGES pages; never truncates.
    """
    messages: list[dict] = []
    for page in range(MESSAGES_MAX_PAGES):
        body = client.get(
            "/api/graph-session-messages/",
            params={
                "session_id": session_id,
                "limit": MESSAGES_PAGE_LIMIT,
                "offset": page * MESSAGES_PAGE_LIMIT,
            },
        ).json()
        messages.extend(body["results"])
        if len(messages) >= body["count"] or not body["results"]:
            return messages
    raise AssertionError(
        f"session {session_id} has {body['count']} messages, more than "
        f"{MESSAGES_MAX_PAGES} pages of {MESSAGES_PAGE_LIMIT}; raise MESSAGES_MAX_PAGES"
    )


def summarize_message(message: dict) -> str:
    message_data = message.get("message_data") or {}
    summary = {
        key: message_data[key]
        for key in ("message_type", "output", "details", "end_node_result")
        if key in message_data
    }
    # Python node messages nest the sandbox result one level down.
    execution = message_data.get("python_code_execution_data") or {}
    summary.update(
        {key: execution[key] for key in ("returncode", "stderr") if key in execution}
    )
    return f"#{message.get('id')} {message.get('name')}: {json.dumps(redact(summary))[:500]}"


def session_diagnostics(client: ApiClient, session_id: int) -> str:
    """Session `status` / `status_data` and its messages, formatted for failure output.

    Never raises: a diagnostics failure must not hide the original one.
    """
    lines = [f"--- diagnostics for session {session_id} ---"]
    try:
        detail = client.get(f"/api/sessions/{session_id}/", expect=None)
        if detail.status_code == 200:
            session = detail.json()
            lines.append(f"status: {session.get('status')}")
            lines.append(f"status_data: {json.dumps(redact(session.get('status_data')))[:2000]}")
        else:
            lines.append(f"session detail -> {detail.status_code}: {body_excerpt(detail)}")
        messages = fetch_session_messages(client, session_id)
        lines.append(f"messages ({len(messages)}):")
        lines.extend(f"  {summarize_message(message)}" for message in messages)
    except Exception as error:  # noqa: BLE001 - diagnostics are best effort by design.
        lines.append(f"diagnostics unavailable: {type(error).__name__}: {error}")
    return "\n".join(lines)


def wait_for_session_status(
    client: ApiClient,
    session_id: int,
    timeout: float,
    interval: float = SESSION_POLL_INTERVAL_SECONDS,
) -> str:
    """Poll the cheap get-updates endpoint until the session is terminal; return its status."""
    return poll(
        lambda: client.get(f"/api/sessions/{session_id}/get-updates/").json()["status"],
        lambda status: status in TERMINAL_SESSION_STATUSES,
        timeout=timeout,
        interval=interval,
        describe=f"session {session_id} to reach a terminal status",
        diagnostics=lambda: session_diagnostics(client, session_id),
    )
