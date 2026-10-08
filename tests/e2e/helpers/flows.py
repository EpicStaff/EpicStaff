"""Create flow A and run flows to a terminal status (shared by warm-up, flow, SSE, load tests)."""

import time
from dataclasses import dataclass

from helpers.api import ApiClient
from helpers.payloads import python_flow_save_payload
from helpers.polling import (
    fetch_session_messages,
    poll,
    session_diagnostics,
    wait_for_session_status,
)

GRAPH_TIME_TO_LIVE_SECONDS = 600


@dataclass(frozen=True)
class CreatedFlow:
    """Response bodies of `POST /api/graphs/` and of the bulk save that follows it."""

    created: dict
    saved: dict

    @property
    def graph_id(self) -> int:
        return self.created["id"]


@dataclass(frozen=True)
class FlowRun:
    session_id: int
    status: str
    run_seconds: float
    run_session_body: dict


def runtime_node_name(node: dict) -> str:
    """The name a node's session messages carry: `"<node_name> #<node id>"`.

    The session manager builds it so two nodes with the same name stay distinguishable.
    """
    return f"{node['node_name']} #{node['id']}"


def create_python_flow(client: ApiClient, name: str) -> CreatedFlow:
    """Create a graph and bulk-save flow A (Start -> Python `a + b` -> End) into it."""
    created = client.post(
        "/api/graphs/",
        json={"name": name, "time_to_live": GRAPH_TIME_TO_LIVE_SECONDS},
        expect=201,
    ).json()
    saved = client.post(
        f"/api/graphs/{created['id']}/save/",
        json=python_flow_save_payload(created["id"], created["save_version"]),
    ).json()
    return CreatedFlow(created, saved)


def start_session(client: ApiClient, graph_id: int, variables: dict) -> dict:
    """POST /api/run-session/; return its body (`{"session_id": int}`).

    A 201 does not mean the run started: a failed listener gate already stores the session
    as `error`. Callers check the status.
    """
    return client.post(
        "/api/run-session/", json={"graph_id": graph_id, "variables": variables}, expect=201
    ).json()


def run_flow_and_wait(client: ApiClient, graph_id: int, variables: dict, timeout: float) -> FlowRun:
    """Start a session and poll it to a terminal status. `run_seconds` covers both."""
    started = time.monotonic()
    body = start_session(client, graph_id, variables)
    status = wait_for_session_status(client, body["session_id"], timeout)
    return FlowRun(body["session_id"], status, time.monotonic() - started, body)


def assert_session_ended(client: ApiClient, session_id: int, status: str) -> None:
    assert status == "end", (
        f"session {session_id} ended with {status!r}\n{session_diagnostics(client, session_id)}"
    )


def wait_for_graph_end(client: ApiClient, session_id: int, timeout: float) -> list[dict]:
    """Poll the session's messages until the `graph_end` row is stored; return them all.

    Django flushes buffered messages to the database every ~3 s, so they lag behind `end`.
    """
    return poll(
        lambda: fetch_session_messages(client, session_id),
        lambda messages: any(
            message["message_data"].get("message_type") == "graph_end" for message in messages
        ),
        timeout=timeout,
        interval=1.0,
        describe=f"the graph_end message of session {session_id}",
        diagnostics=lambda: session_diagnostics(client, session_id),
    )
