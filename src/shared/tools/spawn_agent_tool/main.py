# Spawn Agent Tool
#
# Spawns an ad-hoc, single-purpose sub-agent (role/goal/backstory + a task
# prompt, with an optional LLM config override), runs it as a one-off
# transient flow via the existing `POST /api/run-session/` +
# `GET /api/sessions/<id>/` REST endpoints (the same seam used by the
# proven "Sub-Flow Tool" -- see src/shared/tools/subflow_tool/main.py), and
# returns the sub-agent's output AND its per-spawn token usage.
#
# Unlike the Sub-Flow Tool (which runs an existing, SAVED flow by
# `graph_id`), this tool has no pre-saved flow to point at: the agent is
# defined AD HOC by the tool's own arguments. There is no REST endpoint that
# accepts an inline/ephemeral graph or agent definition, so this tool builds
# the smallest possible runnable flow -- one Agent, one Crew (with that one
# agent), one Task (the caller's prompt), and a Graph with
# start -> crew_node -> end -- entirely out of EXISTING model endpoints
# (`/agents/`, `/crews/`, `/tasks/`, `/graphs/`, `/startnodes/`,
# `/crewnodes/`, `/endnodes/`, `/edges/`). No new Django model, migration,
# ORM column, canvas node type or tool-kind is introduced anywhere for this
# feature: every row created here is a plain row of an already-existing
# model, and every single one of them is deleted again in a `finally` block
# once the spawned sub-agent finishes (or fails, or times out) -- nothing is
# left behind.
#
# `api_key`, `api_base_url`, `default_llm_config_id` and `poll_timeout_s` are
# NOT function parameters: they are declared in args_schema.json with
# "input_type": "user_input", so they are seeded as tool CONFIG variables
# (set once when the tool is configured for an agent) rather than
# agent-callable arguments. The sandbox executor injects configured values as
# module-level globals before this function runs -- see `globals().get(...)`
# below.
#
# `session_id` is a different kind of global: it is NOT declared in
# args_schema.json at all. It is injected by the crew engine for every
# built-in python-code tool call (see `global_kwargs["session_id"]` in
# src/crew/services/graph/nodes/crew_node.py) so a tool can know which
# session is calling it. This tool uses it for two things, exactly mirroring
# the Sub-Flow Tool:
#   1. `parent_session_id` on the sub-agent run, so the new sub-session
#      links back to the caller via the existing Session.parent_session
#      self-FK. The server (`RunSession.post`, see
#      tests/api_tests/run_session_parent_org_test.py) enforces that
#      `parent_session_id` only links when the parent session's organization
#      matches the target graph's organization -- so a spawn only succeeds
#      when the caller's session org matches the org of the graph this tool
#      just created (currently always DEFAULT_ORGANIZATION, since
#      `GraphViewSet` hardcodes new graphs to it -- a separate, pre-existing
#      API limitation). No client-side org check is added here; the server
#      boundary is what protects it, and a same-org mismatch surfaces as a
#      400 from `/run-session/`, which this tool translates into a readable
#      "known multi-org limitation" error (see `_translate_run_session_error`
#      below) instead of a raw HTTP status/body.
#   2. A recursion/depth guard: before spawning, this tool walks the
#      parent_session chain (via GET /api/sessions/<id>/) starting at the
#      caller's own session and refuses to spawn another sub-agent if the
#      chain is already at the maximum allowed depth (an agent spawning
#      agents spawning agents...). Unlike the Sub-Flow Tool's guard, there is
#      no fixed `graph_id` to detect a literal cycle against (every spawn
#      builds a brand-new, disposable graph), so this is a pure depth cap.

import json
import time
import uuid

try:
    from loguru import logger
except ImportError:  # pragma: no cover - sandbox venv without loguru installed

    class _NoOpLogger:
        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    logger = _NoOpLogger()

DEFAULT_API_BASE_URL = "http://django_app:8000/api"
DEFAULT_POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 2.0
HTTP_TIMEOUT_S = 15.0
MAX_SPAWN_DEPTH = 5
TERMINAL_STATUSES = {"end", "error", "stop", "expired"}
FAILURE_STATUSES = {"error", "stop", "expired"}

DEFAULT_ROLE = "Assistant"
DEFAULT_BACKSTORY = "A focused, single-purpose assistant spawned to complete one specific task."
DEFAULT_EXPECTED_OUTPUT = "A clear, complete answer to the given task."
OUTPUT_VARIABLE_PATH = "result"


def _api_base_url() -> str:
    import os

    configured = globals().get("api_base_url")
    if configured:
        return str(configured).rstrip("/")

    env_url = os.environ.get("DJANGO_API_URL")
    if env_url:
        return env_url.rstrip("/")

    return DEFAULT_API_BASE_URL


def _headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Content-Type": "application/json"}


def _get_session_or_raise(client, base_url: str, headers: dict, session_id) -> dict:
    response = client.get(f"{base_url}/sessions/{session_id}/", headers=headers)
    if response.status_code != 200:
        raise RuntimeError(
            f"could not read session {session_id} (status {response.status_code}): "
            f"{response.text[:300]}"
        )
    return response.json()


def _check_spawn_depth(client, base_url: str, headers: dict, current_session_id):
    """
    Walk the parent_session chain starting from the caller's own session and
    refuse to spawn if it is already at the maximum allowed depth. Returns a
    readable error string if the call must be refused, else None.
    """
    session_id = current_session_id
    depth = 0

    while session_id is not None:
        depth += 1
        if depth > MAX_SPAWN_DEPTH:
            return (
                f"Error: agent-spawn call chain is already {depth - 1} level(s) "
                f"deep (max allowed: {MAX_SPAWN_DEPTH}). Refusing to spawn another "
                f"nested sub-agent to avoid runaway recursion."
            )

        try:
            data = _get_session_or_raise(client, base_url, headers, session_id)
        except RuntimeError as e:
            # Can't verify ancestry (session removed, org-scoping, etc.) — fail
            # closed with a readable error rather than silently skipping the guard.
            return f"Error: could not verify agent-spawn recursion safety: {e}"

        session_id = data.get("parent_session")

    return None


class _CreationFailed(Exception):
    """Internal control-flow exception: carries the already-formatted error string."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _post(client, base_url: str, path: str, payload: dict, headers: dict, what: str) -> dict:
    try:
        response = client.post(f"{base_url}{path}", json=payload, headers=headers)
    except Exception as e:  # httpx.HTTPError and friends
        raise _CreationFailed(
            f"Error: could not reach the EpicStaff API while creating {what}: {str(e)[:300]}"
        )

    if response.status_code not in (200, 201):
        raise _CreationFailed(
            f"Error: failed to create {what}, status {response.status_code}: "
            f"{response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as e:
        raise _CreationFailed(f"Error: unexpected response creating {what}: {e}")


def _translate_run_session_error(status_code: int, body_text: str, graph_id) -> str:
    """
    Turn a failed POST /run-session/ response into a readable error string.

    In particular, detect the server-side org-mismatch rejection (see
    `RunSession.post` in tables/views/views.py: it 400s with a "Parent
    session does not belong to the same organization as the target graph."
    message when `parent_session_id`'s org differs from the target graph's
    org) and translate it into an actionable message that explains the known
    multi-org limitation, instead of surfacing the raw 400 body.
    """
    if status_code == 400 and "organization" in body_text.lower():
        return (
            "Error: cannot spawn a sub-agent -- the parent session's "
            "organization does not match the spawned graph's organization "
            "(sub-agent spawn currently runs in the default organization). "
            "This is a known multi-org limitation."
        )
    return (
        "Error: failed to start spawned sub-agent (graph_id="
        f"{graph_id}), status {status_code}: {body_text[:300]}"
    )


def _delete_quietly(client, base_url: str, path: str, headers: dict, what: str) -> None:
    """Best-effort cleanup — logs a warning on failure but never raises."""
    try:
        response = client.delete(f"{base_url}{path}", headers=headers)
        if response.status_code not in (200, 202, 204, 404):
            logger.warning(
                "spawn_agent_tool: failed to clean up {} at {} (status {}): {}",
                what,
                path,
                response.status_code,
                response.text[:300],
            )
    except Exception as e:
        logger.warning("spawn_agent_tool: error cleaning up {} at {}: {}", what, path, e)


def main(
    prompt: str | None = None,
    role: str | None = None,
    goal: str | None = None,
    backstory: str | None = None,
    expected_output: str | None = None,
    llm_config_id: int | None = None,
    **kwargs,
) -> str:
    """
    Spawn an ad-hoc sub-agent, run it once on `prompt`, and return its output
    together with its per-spawn token usage. Never raises: all failures are
    returned as readable error strings. All transient rows created to run
    the sub-agent are deleted again before returning, even on failure.
    """
    created = {
        "agent_id": None,
        "crew_id": None,
        "task_id": None,
        "graph_id": None,
    }

    try:
        import httpx

        api_key = globals().get("api_key")
        default_llm_config_id = globals().get("default_llm_config_id")
        poll_timeout_s = globals().get("poll_timeout_s")
        if poll_timeout_s is None:
            poll_timeout_s = DEFAULT_POLL_TIMEOUT_S
        current_session_id = globals().get("session_id")
        if current_session_id is None:
            logger.warning(
                "spawn_agent_tool: no caller session_id injected -- recursion "
                "guard and parent_session linkage are disabled for this run."
            )

        if not prompt or not str(prompt).strip():
            return (
                "Error: 'prompt' is missing. Provide the task/instructions for "
                "the spawned sub-agent."
            )
        if not api_key:
            return (
                "Error: 'api_key' is missing. Configure an EpicStaff API key for "
                "this tool before using the Spawn Agent Tool."
            )

        effective_llm_config_id = llm_config_id or default_llm_config_id
        if not effective_llm_config_id:
            return (
                "Error: no LLM config available. Either pass 'llm_config_id' or "
                "configure 'default_llm_config_id' for this tool."
            )

        base_url = _api_base_url()
        headers = _headers(api_key)

        with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
            if current_session_id is not None:
                depth_error = _check_spawn_depth(
                    client, base_url, headers, current_session_id
                )
                if depth_error:
                    return depth_error

            unique_suffix = uuid.uuid4().hex[:12]

            try:
                agent_data = _post(
                    client,
                    base_url,
                    "/agents/",
                    {
                        "role": role or DEFAULT_ROLE,
                        "goal": goal or f"Complete the following task: {prompt}",
                        "backstory": backstory or DEFAULT_BACKSTORY,
                        "llm_config": effective_llm_config_id,
                    },
                    headers,
                    "spawned agent",
                )
                created["agent_id"] = agent_data["id"]

                crew_data = _post(
                    client,
                    base_url,
                    "/crews/",
                    {
                        "name": f"spawn-agent-crew-{unique_suffix}",
                        "agents": [created["agent_id"]],
                        "process": "sequential",
                    },
                    headers,
                    "spawned crew",
                )
                created["crew_id"] = crew_data["id"]

                task_data = _post(
                    client,
                    base_url,
                    "/tasks/",
                    {
                        "crew": created["crew_id"],
                        "agent": created["agent_id"],
                        "name": f"spawn-agent-task-{unique_suffix}",
                        "instructions": prompt,
                        "expected_output": expected_output or DEFAULT_EXPECTED_OUTPUT,
                        "order": 0,
                    },
                    headers,
                    "spawned task",
                )
                created["task_id"] = task_data["id"]

                graph_data = _post(
                    client,
                    base_url,
                    "/graphs/",
                    {"name": f"spawn-agent-flow-{unique_suffix}"},
                    headers,
                    "spawned flow",
                )
                created["graph_id"] = graph_data["id"]
                graph_id = created["graph_id"]

                start_node_data = _post(
                    client,
                    base_url,
                    "/startnodes/",
                    {"graph": graph_id, "variables": {"variables": {}}},
                    headers,
                    "spawned flow's start node",
                )

                crew_node_data = _post(
                    client,
                    base_url,
                    "/crewnodes/",
                    {
                        "graph": graph_id,
                        "crew_id": created["crew_id"],
                        "output_variable_path": OUTPUT_VARIABLE_PATH,
                    },
                    headers,
                    "spawned flow's crew node",
                )

                end_node_data = _post(
                    client,
                    base_url,
                    "/endnodes/",
                    {
                        "graph": graph_id,
                        "output_map": {
                            OUTPUT_VARIABLE_PATH: f"variables.{OUTPUT_VARIABLE_PATH}"
                        },
                    },
                    headers,
                    "spawned flow's end node",
                )

                _post(
                    client,
                    base_url,
                    "/edges/",
                    {
                        "graph": graph_id,
                        "start_node_id": start_node_data["id"],
                        "end_node_id": crew_node_data["id"],
                    },
                    headers,
                    "spawned flow's start edge",
                )
                _post(
                    client,
                    base_url,
                    "/edges/",
                    {
                        "graph": graph_id,
                        "start_node_id": crew_node_data["id"],
                        "end_node_id": end_node_data["id"],
                    },
                    headers,
                    "spawned flow's end edge",
                )
            except _CreationFailed as e:
                return e.message

            payload = {"graph_id": graph_id, "variables": {}}
            if current_session_id is not None:
                payload["parent_session_id"] = current_session_id

            try:
                start_response = client.post(
                    f"{base_url}/run-session/", json=payload, headers=headers
                )
            except httpx.HTTPError as e:
                return (
                    "Error: could not reach the EpicStaff API to start the "
                    f"spawned sub-agent: {str(e)[:300]}"
                )

            if start_response.status_code not in (200, 201):
                return _translate_run_session_error(
                    start_response.status_code, start_response.text, graph_id
                )

            try:
                sub_session_id = start_response.json()["session_id"]
            except (ValueError, KeyError) as e:
                return (
                    "Error: unexpected response starting spawned sub-agent "
                    f"(graph_id={graph_id}): {e}"
                )

            deadline = time.monotonic() + poll_timeout_s
            session_data = None
            status = None

            try:
                while True:
                    try:
                        session_data = _get_session_or_raise(
                            client, base_url, headers, sub_session_id
                        )
                    except RuntimeError as e:
                        return f"Error: {e}"

                    status = session_data.get("status")
                    if status in TERMINAL_STATUSES:
                        break

                    if time.monotonic() >= deadline:
                        return (
                            f"Error: spawned sub-agent session {sub_session_id} "
                            f"did not finish within {poll_timeout_s}s (last "
                            f"status: '{status}')."
                        )

                    time.sleep(POLL_INTERVAL_S)
            except httpx.HTTPError as e:
                return (
                    "Error: could not reach the EpicStaff API while polling "
                    f"spawned sub-agent session {sub_session_id}: {str(e)[:300]}"
                )

            if status in FAILURE_STATUSES:
                reason = (session_data.get("status_data") or {}).get("reason")
                if not reason:
                    reason = f"session ended with status '{status}'"
                return (
                    f"Error: spawned sub-agent session {sub_session_id} failed: "
                    f"{reason}"
                )

            output_variables = session_data.get("variables") or {}
            output = output_variables.get(OUTPUT_VARIABLE_PATH, output_variables)
            token_usage = session_data.get("token_usage") or {}

            result = {
                "output": output,
                "token_usage": token_usage,
                "session_id": sub_session_id,
            }
            try:
                return json.dumps(result)
            except TypeError:
                return str(result)
    except Exception as e:
        return f"Error: spawn agent tool failed. Unexpected exception: {e}"
    finally:
        _cleanup(created)


def _cleanup(created: dict) -> None:
    """
    Deletes every transient row created for this spawn, even on failure.
    Deleting the Graph cascades its StartNode/EndNode/CrewNode/Edges (all
    have `on_delete=CASCADE` back to Graph), so only the Graph, Task, Crew
    and Agent need explicit deletes here.
    """
    api_key = globals().get("api_key")
    if not api_key:
        return

    try:
        import httpx
    except ImportError:
        return

    base_url = _api_base_url()
    headers = _headers(api_key)

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
            if created.get("graph_id"):
                _delete_quietly(
                    client, base_url, f"/graphs/{created['graph_id']}/", headers, "graph"
                )
            if created.get("task_id"):
                _delete_quietly(
                    client, base_url, f"/tasks/{created['task_id']}/", headers, "task"
                )
            if created.get("crew_id"):
                _delete_quietly(
                    client, base_url, f"/crews/{created['crew_id']}/", headers, "crew"
                )
            if created.get("agent_id"):
                _delete_quietly(
                    client, base_url, f"/agents/{created['agent_id']}/", headers, "agent"
                )
    except Exception as e:
        logger.warning("spawn_agent_tool: cleanup pass failed entirely: {}", e)
