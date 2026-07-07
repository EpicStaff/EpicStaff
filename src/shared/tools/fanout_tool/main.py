# Fan-Out Tool
#
# Runs saved EpicStaff flows (graphs) in a fan-out pattern, on top of the
# exact same `POST /api/run-session/` + `GET /api/sessions/<id>/` REST
# contract used by subflow_tool/main.py. Two modes, selected via the
# agent-supplied `mode` argument:
#
#   * "parallel" — one configured `graph_id`, many `items` (each a
#     variables dict). All items are started concurrently (bounded worker
#     pool) and this call blocks until ALL of them finish (a barrier),
#     returning results in the same order as `items`. A failed item does
#     not abort the others — its slot in `results` is an error entry.
#
#   * "pipeline" — an ordered configured `graph_ids` list ("stages") and a
#     single agent-supplied `input`. Stage 1 runs with `input`; each
#     following stage receives the previous stage's output as its input.
#     No barrier — stages run strictly sequentially. A failed stage stops
#     the chain immediately and the whole call returns that error.
#
# `graph_id`, `graph_ids`, `api_key`, `api_base_url`, `poll_timeout_s`,
# `max_items` and `max_workers` are NOT function parameters: they are
# declared in args_schema.json with "input_type": "user_input", so they are
# seeded as tool CONFIG variables (set once when the tool is configured for
# an agent) rather than agent-callable arguments — mirrors subflow_tool.
#
# `session_id` is injected by the crew engine for every built-in
# python-code tool call (see `global_kwargs["session_id"]` in
# src/crew/services/graph/nodes/crew_node.py). This tool reuses it exactly
# as subflow_tool does:
#   1. As `parent_session_id` on each child sub-flow run, so the new
#      sub-session links back to the calling session via the existing
#      Session.parent_session self-FK.
#   2. For the SAME recursion guard as subflow_tool (`_check_recursion`,
#      walking the parent_session chain and refusing to run if the target
#      graph_id already appears in it, or the chain is already at
#      MAX_SUBFLOW_DEPTH). This guard is reused verbatim (not weakened) so
#      that a fan-out nested inside another fan-out (or inside an ordinary
#      sub-flow) still cannot recurse unbounded.
#
# NOTE ON DUPLICATION: sandboxed built-in tools are self-contained single
# main.py files and cannot import from one another, so the run/poll/
# ownership/recursion helpers below are intentionally duplicated (not
# imported) from subflow_tool/main.py, kept as close to verbatim as
# possible. If a shared library becomes available to sandboxed tools in the
# future, these helpers should be extracted there instead.

import concurrent.futures
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
MAX_SUBFLOW_DEPTH = 5  # identical cap/name to subflow_tool.py — do not weaken
MAX_FANOUT_ITEMS = 10  # cap on parallel items / pipeline stages per call
MAX_FANOUT_WORKERS = 4  # cap on concurrent sub-flow runs in parallel mode
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

    Verbatim copy of subflow_tool._check_recursion — see the module
    docstring above for why this is duplicated rather than imported.
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


def _run_subflow_and_wait(base_url, headers, graph_id, variables, poll_timeout_s, parent_session_id):
    """
    Start a single saved flow (graph_id) as a sub-flow, poll it to
    completion and return its output. Never raises.

    Mirrors subflow_tool.main()'s run+poll logic exactly (minus the
    graph_id/api_key presence checks and the recursion guard, which are the
    caller's responsibility here since they only need to run once per
    fan-out call, not once per child).

    Returns a 3-tuple:
        (True, output_variables: dict, child_session_id) on success
        (False, error_message: str, None) on failure
    """
    import httpx

    try:
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                payload = {"graph_id": graph_id, "variables": variables}
                if parent_session_id is not None:
                    payload["parent_session_id"] = parent_session_id
                start_response = client.post(
                    f"{base_url}/run-session/", json=payload, headers=headers
                )
        except httpx.HTTPError as e:
            return (
                False,
                f"could not reach the EpicStaff API to start sub-flow "
                f"(graph_id={graph_id}): {str(e)[:300]}",
                None,
            )

        if start_response.status_code not in (200, 201):
            return (
                False,
                f"failed to start sub-flow (graph_id={graph_id}), status "
                f"{start_response.status_code}: {start_response.text[:300]}",
                None,
            )

        try:
            sub_session_id = start_response.json()["session_id"]
        except (ValueError, KeyError) as e:
            return (
                False,
                f"unexpected response starting sub-flow (graph_id={graph_id}): {e}",
                None,
            )

        deadline = time.monotonic() + poll_timeout_s
        session_data = None
        status = None

        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                while True:
                    try:
                        session_data = _get_session_or_raise(
                            client, base_url, headers, sub_session_id
                        )
                    except RuntimeError as e:
                        return False, str(e), None

                    status = session_data.get("status")
                    if status in TERMINAL_STATUSES:
                        break

                    if time.monotonic() >= deadline:
                        return (
                            False,
                            f"sub-flow session {sub_session_id} (graph_id={graph_id}) "
                            f"did not finish within {poll_timeout_s}s "
                            f"(last status: '{status}').",
                            None,
                        )

                    time.sleep(POLL_INTERVAL_S)
        except httpx.HTTPError as e:
            return (
                False,
                f"could not reach the EpicStaff API while polling sub-flow session "
                f"{sub_session_id}: {str(e)[:300]}",
                None,
            )

        if status in FAILURE_STATUSES:
            reason = (session_data.get("status_data") or {}).get("reason")
            if not reason:
                reason = f"session ended with status '{status}'"
            return (
                False,
                f"sub-flow session {sub_session_id} (graph_id={graph_id}) failed: {reason}",
                None,
            )

        output_variables = session_data.get("variables") or {}
        return True, output_variables, sub_session_id
    except Exception as e:
        return (
            False,
            f"unexpected exception running sub-flow (graph_id={graph_id}): {e}",
            None,
        )


def _run_parallel(items, api_key, base_url, headers, poll_timeout_s, current_session_id) -> str:
    import httpx

    graph_id = globals().get("graph_id")
    if not graph_id:
        return (
            "Error: 'graph_id' is missing. Configure which saved flow to fan out "
            "over for parallel mode."
        )

    if not items:
        return (
            "Error: 'items' must be a non-empty JSON array — one input payload "
            "(variables dict) per concurrent sub-flow run."
        )
    if not isinstance(items, list):
        return "Error: 'items' must be a JSON array (list)."

    max_items = globals().get("max_items") or MAX_FANOUT_ITEMS
    original_count = len(items)
    truncated = original_count > max_items
    if truncated:
        items = items[:max_items]
        logger.warning(
            f"fanout_tool: truncated 'items' from {original_count} to {max_items} "
            f"(MAX_FANOUT_ITEMS cap)."
        )

    # Recursion guard runs once — every item targets the same graph_id and
    # links to the same caller session, so a single ancestor-chain walk
    # covers all of them.
    if current_session_id is not None:
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                recursion_error = _check_recursion(
                    client, base_url, headers, current_session_id, graph_id
                )
        except httpx.HTTPError as e:
            return (
                "Error: could not reach the EpicStaff API to verify recursion "
                f"safety: {str(e)[:300]}"
            )
        if recursion_error:
            return recursion_error
    else:
        logger.warning(
            "fanout_tool: no caller session_id injected -- recursion guard and "
            "parent_session linkage are disabled for this parallel run."
        )

    results: list = [None] * len(items)
    runnable_indices = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            results[idx] = {
                "error": (
                    f"item at index {idx} must be a JSON object (dict), got "
                    f"{type(item).__name__}"
                )
            }
            continue
        runnable_indices.append(idx)

    max_workers = globals().get("max_workers") or MAX_FANOUT_WORKERS
    workers = max(1, min(max_workers, len(runnable_indices) or 1))

    if runnable_indices:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(
                    _run_subflow_and_wait,
                    base_url,
                    headers,
                    graph_id,
                    items[idx],
                    poll_timeout_s,
                    current_session_id,
                ): idx
                for idx in runnable_indices
            }
            for future in concurrent.futures.as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    ok, payload, _child_session_id = future.result()
                except Exception as e:  # pragma: no cover - defensive, workers never raise
                    ok, payload = False, f"unexpected exception: {e}"
                results[idx] = payload if ok else {"error": payload}

    output = {"mode": "parallel", "results": results}
    if truncated:
        output["truncated"] = True
        output["requested_items"] = original_count
        output["used_items"] = len(items)

    try:
        return json.dumps(output)
    except TypeError:
        return str(output)


def _run_pipeline(input_payload, api_key, base_url, headers, poll_timeout_s, current_session_id) -> str:
    import httpx

    graph_ids = globals().get("graph_ids")
    if not graph_ids or not isinstance(graph_ids, list):
        return (
            "Error: 'graph_ids' is missing or empty. Configure an ordered list of "
            "saved flow (graph) IDs to run as pipeline stages."
        )

    max_items = globals().get("max_items") or MAX_FANOUT_ITEMS
    if len(graph_ids) > max_items:
        return (
            f"Error: pipeline has {len(graph_ids)} stage(s), exceeding the maximum "
            f"of {max_items} allowed (MAX_FANOUT_ITEMS). Reduce 'graph_ids' or "
            "raise the 'max_items' configuration."
        )

    if input_payload is not None and not isinstance(input_payload, dict):
        return "Error: 'input' must be a JSON object (dict)."
    stage_input = input_payload or {}

    if current_session_id is None:
        logger.warning(
            "fanout_tool: no caller session_id injected -- recursion guard and "
            "parent_session linkage are disabled for this pipeline run."
        )

    link_session_id = current_session_id
    stage_outputs = []

    for idx, gid in enumerate(graph_ids):
        if not gid:
            return f"Error: graph_ids[{idx}] is missing or invalid."

        if link_session_id is not None:
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                    recursion_error = _check_recursion(
                        client, base_url, headers, link_session_id, gid
                    )
            except httpx.HTTPError as e:
                return (
                    f"Error: could not reach the EpicStaff API to verify recursion "
                    f"safety for pipeline stage {idx} (graph_id={gid}): "
                    f"{str(e)[:300]}"
                )
            if recursion_error:
                return recursion_error

        ok, payload, child_session_id = _run_subflow_and_wait(
            base_url, headers, gid, stage_input, poll_timeout_s, link_session_id
        )
        if not ok:
            return (
                f"Error: pipeline stage {idx} (graph_id={gid}) failed: {payload}"
            )

        stage_outputs.append(payload)
        stage_input = payload
        link_session_id = child_session_id

    output = {
        "mode": "pipeline",
        "final_output": stage_outputs[-1],
        "stage_outputs": stage_outputs,
    }
    try:
        return json.dumps(output)
    except TypeError:
        return str(output)


def main(
    mode: str | None = None,
    items: list | None = None,
    input: dict | None = None,
    **kwargs,
) -> str:
    """
    Fan out over saved flows in either 'parallel' (barrier) or 'pipeline'
    (sequential chaining) mode. Never raises: all failures are returned as
    readable error strings.
    """
    try:
        if mode not in ("parallel", "pipeline"):
            return (
                "Error: 'mode' must be either 'parallel' or 'pipeline' "
                f"(got: {mode!r})."
            )

        api_key = globals().get("api_key")
        if not api_key:
            return (
                "Error: 'api_key' is missing. Configure an EpicStaff API key for "
                "this tool before using the Fan-Out Tool."
            )

        poll_timeout_s = globals().get("poll_timeout_s")
        if poll_timeout_s is None:
            poll_timeout_s = DEFAULT_POLL_TIMEOUT_S

        current_session_id = globals().get("session_id")

        base_url = _api_base_url()
        headers = _headers(api_key)

        if mode == "parallel":
            return _run_parallel(
                items, api_key, base_url, headers, poll_timeout_s, current_session_id
            )

        return _run_pipeline(
            input, api_key, base_url, headers, poll_timeout_s, current_session_id
        )
    except Exception as e:
        return f"Error: fan-out tool failed. Unexpected exception: {e}"
