# Sub-Flow Tool
#
# Runs another saved EpicStaff flow (graph) as a sub-flow via the existing
# `POST /api/run-session/` + `GET /api/sessions/<id>/` REST endpoints, and
# returns the sub-flow's final output (Session.variables) as the tool result.
#
# `graph_id`, `api_key`, `api_base_url` and `poll_timeout_s` are NOT function
# parameters: they are declared in args_schema.json with
# "input_type": "user_input", so they are seeded as tool CONFIG variables (set
# once when the tool is configured for an agent) rather than agent-callable
# arguments. The sandbox executor injects configured values as module-level
# globals before this function runs — see `globals().get(...)` below.
#
# `session_id` is a different kind of global: it is NOT declared in
# args_schema.json at all. It is injected by the crew engine for every
# built-in python-code tool call (see `global_kwargs["session_id"]` in
# src/crew/services/graph/nodes/crew_node.py) so a tool can know which
# session is calling it. This tool uses it for two things:
#   1. `parent_session_id` on the sub-flow run, so the new sub-session links
#      back to the caller via the existing Session.parent_session self-FK.
#   2. A recursion guard: before starting the sub-flow, this tool walks the
#      parent_session chain (via GET /api/sessions/<id>/) starting at the
#      caller's own session and refuses to run if the target graph_id already
#      appears in that ancestor chain, or if the chain is already at the
#      maximum allowed depth.

import json
import time

try:
    from loguru import logger
except ImportError:  # pragma: no cover - sandbox venv without loguru installed

    class _NoOpLogger:
        def warning(self, *args, **kwargs):
            pass

    logger = _NoOpLogger()

DEFAULT_API_BASE_URL = "http://django_app:8000/api"
DEFAULT_POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 2.0
HTTP_TIMEOUT_S = 15.0
MAX_SUBFLOW_DEPTH = 5
TERMINAL_STATUSES = {"end", "error", "stop", "expired"}
FAILURE_STATUSES = {"error", "stop", "expired"}


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


def _check_recursion(
    client, base_url: str, headers: dict, current_session_id, target_graph_id
):
    """
    Walk the parent_session chain starting from the caller's own session.
    Returns a readable error string if the call must be refused, else None.
    """
    session_id = current_session_id
    chain = []
    depth = 0

    while session_id is not None:
        depth += 1
        if depth > MAX_SUBFLOW_DEPTH:
            return (
                f"Error: sub-flow call chain is already {depth - 1} level(s) deep "
                f"(max allowed: {MAX_SUBFLOW_DEPTH}). Refusing to start another "
                f"nested sub-flow to avoid runaway recursion. Chain so far: {chain}."
            )

        try:
            data = _get_session_or_raise(client, base_url, headers, session_id)
        except RuntimeError as e:
            # Can't verify ancestry (session removed, org-scoping, etc.) — fail
            # closed with a readable error rather than silently skipping the guard.
            return f"Error: could not verify sub-flow recursion safety: {e}"

        graph_id = data.get("graph")
        chain.append(graph_id)

        if graph_id is not None and graph_id == target_graph_id:
            return (
                f"Error: refusing to run sub-flow (graph_id={target_graph_id}) — it "
                f"already appears in the calling chain {chain}, which would create "
                f"infinite recursion."
            )

        session_id = data.get("parent_session")

    return None


def main(input_variables: dict | None = None, **kwargs) -> str:
    """
    Run a saved flow (graph) as a sub-flow and return its final output.
    Never raises: all failures are returned as readable error strings.
    """
    try:
        import httpx

        graph_id = globals().get("graph_id")
        api_key = globals().get("api_key")
        poll_timeout_s = globals().get("poll_timeout_s")
        if poll_timeout_s is None:
            poll_timeout_s = DEFAULT_POLL_TIMEOUT_S
        current_session_id = globals().get("session_id")
        if current_session_id is None:
            # Non-fatal degradation: happens when the tool is invoked outside
            # a crew-engine session context (e.g. ad-hoc/manual invocation).
            # The recursion guard and parent_session linkage are both no-ops
            # in this case -- surface it so it isn't silently skipped.
            logger.warning(
                "subflow_tool: no caller session_id injected -- recursion "
                "guard and parent_session linkage are disabled for this run."
            )

        if not graph_id:
            return (
                "Error: 'graph_id' is missing. Configure which saved flow to run "
                "for this tool before using the Sub-Flow Tool."
            )
        if not api_key:
            return (
                "Error: 'api_key' is missing. Configure an EpicStaff API key for "
                "this tool before using the Sub-Flow Tool."
            )

        input_variables = input_variables or {}
        if not isinstance(input_variables, dict):
            return "Error: 'input_variables' must be a JSON object (dict)."

        base_url = _api_base_url()
        headers = _headers(api_key)

        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                if current_session_id is not None:
                    recursion_error = _check_recursion(
                        client, base_url, headers, current_session_id, graph_id
                    )
                    if recursion_error:
                        return recursion_error

                payload = {"graph_id": graph_id, "variables": input_variables}
                if current_session_id is not None:
                    payload["parent_session_id"] = current_session_id

                start_response = client.post(
                    f"{base_url}/run-session/", json=payload, headers=headers
                )
        except httpx.HTTPError as e:
            return (
                "Error: could not reach the EpicStaff API to start the sub-flow: "
                f"{str(e)[:300]}"
            )

        if start_response.status_code not in (200, 201):
            return (
                f"Error: failed to start sub-flow (graph_id={graph_id}), status "
                f"{start_response.status_code}: {start_response.text[:300]}"
            )

        try:
            sub_session_id = start_response.json()["session_id"]
        except (ValueError, KeyError) as e:
            return f"Error: unexpected response starting sub-flow (graph_id={graph_id}): {e}"

        deadline = time.monotonic() + poll_timeout_s
        session_data = None

        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
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
                            f"Error: sub-flow session {sub_session_id} "
                            f"(graph_id={graph_id}) did not finish within "
                            f"{poll_timeout_s}s (last status: '{status}')."
                        )

                    time.sleep(POLL_INTERVAL_S)
        except httpx.HTTPError as e:
            return (
                f"Error: could not reach the EpicStaff API while polling sub-flow "
                f"session {sub_session_id}: {str(e)[:300]}"
            )

        if status in FAILURE_STATUSES:
            reason = (session_data.get("status_data") or {}).get("reason")
            if not reason:
                reason = f"session ended with status '{status}'"
            return (
                f"Error: sub-flow session {sub_session_id} (graph_id={graph_id}) "
                f"failed: {reason}"
            )

        output_variables = session_data.get("variables") or {}
        try:
            return json.dumps(output_variables)
        except TypeError:
            return str(output_variables)
    except Exception as e:
        return f"Error: sub-flow tool failed. Unexpected exception: {e}"
