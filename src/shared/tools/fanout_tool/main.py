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
#
# RESILIENCE NOTE: a fan-out call can issue a lot of HTTP requests (one poll
# GET roughly every POLL_INTERVAL_S per in-flight item, for up to
# poll_timeout_s), which is enough traffic against a single-worker dev
# server to occasionally see a connection get dropped mid-response
# (httpx.RemoteProtocolError: "server disconnected without sending a
# response"). Three things below address that:
#   1. One pooled httpx.Client is shared for the whole fan-out call (see
#      `_new_http_client`) instead of opening a fresh client per request,
#      cutting connection churn. httpx.Client is documented as thread-safe
#      for concurrent requests, so the same instance is safely shared across
#      the ThreadPoolExecutor workers used by parallel mode.
#   2. The initial POST /run-session/ retries a bounded number of times on a
#      transient error (see `_post_run_session_with_retry`).
#   3. Each poll GET treats a transient error as non-fatal (see
#      `_poll_get_session` / `_poll_until_terminal`): it's logged and
#      retried with backoff rather than aborting the item, since the
#      sub-flow itself is very likely still running server-side. Only a
#      real terminal status, the overall `poll_timeout_s` deadline, or too
#      many *consecutive* transient failures in a row ends the poll.

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

DEFAULT_API_BASE_URL = "http://djangoapp:8000/api"
DEFAULT_POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 2.0
HTTP_TIMEOUT_S = 15.0
MAX_SUBFLOW_DEPTH = 5  # identical cap/name to subflow_tool.py — do not weaken
MAX_FANOUT_ITEMS = 10  # cap on parallel items / pipeline stages per call
MAX_FANOUT_WORKERS = 4  # cap on concurrent sub-flow runs in parallel mode
TERMINAL_STATUSES = {"end", "error", "stop", "expired"}
FAILURE_STATUSES = {"error", "stop", "expired"}

# --- transient-connection-error resilience knobs -----------------------
# A transient error here means the exact class of failure QA hit repeatedly:
# httpx.RemoteProtocolError ("server disconnected without sending a
# response"), httpx.ConnectError, httpx.ReadError, or a 5xx response — all
# treated as "the API is momentarily unreachable", not "the sub-flow died".
POST_MAX_ATTEMPTS = 3  # initial POST /run-session/: total attempts before giving up
POST_BACKOFF_BASE_S = 0.5  # doubles each retry: 0.5s, 1.0s, ...
MAX_CONSECUTIVE_POLL_ERRORS = 5  # consecutive transient poll failures before giving up
MAX_POLL_ERROR_BACKOFF_S = 20.0  # cap on the doubling poll-retry backoff


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


def _new_http_client(pool_size: int):
    """
    Build a single pooled httpx.Client to be reused for every request made
    during ONE fan-out call (the recursion check(s), the initial POST(s),
    and every poll GET) instead of opening a fresh client per request.

    This is what actually cuts the connection churn that produces "server
    disconnected without sending a response" (httpx.RemoteProtocolError)
    against a single-worker dev Django server: previously every POST and
    every one of the ~150 poll GETs per item opened (and tore down) its own
    TCP connection.

    httpx.Client is documented as thread-safe for issuing requests
    concurrently — the underlying connection pool has its own internal
    locking — so ONE shared client instance is used here (not one client per
    worker) and is safely passed into every ThreadPoolExecutor worker in
    parallel mode.
    """
    import httpx

    size = max(pool_size, 1)
    limits = httpx.Limits(max_connections=size + 2, max_keepalive_connections=size)
    return httpx.Client(timeout=HTTP_TIMEOUT_S, limits=limits)


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


def _post_run_session_with_retry(client, base_url, headers, payload, graph_id):
    """
    POST /run-session/ with a bounded retry on a transient error
    (httpx.RemoteProtocolError / ConnectError / ReadError, or a 5xx
    response). Small exponential backoff between attempts
    (POST_BACKOFF_BASE_S, POST_BACKOFF_BASE_S * 2, ...).

    Returns (response, error_message): exactly one of the two is None.
    """
    import httpx

    attempt = 0
    while True:
        attempt += 1
        try:
            response = client.post(
                f"{base_url}/run-session/", json=payload, headers=headers
            )
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as e:
            if attempt >= POST_MAX_ATTEMPTS:
                return None, (
                    f"could not reach the EpicStaff API to start sub-flow "
                    f"(graph_id={graph_id}) -- gave up after {attempt} attempt(s) "
                    f"due to a transient connection error ({type(e).__name__}): "
                    f"{str(e)[:300]}"
                )
            backoff = POST_BACKOFF_BASE_S * (2 ** (attempt - 1))
            logger.warning(
                f"fanout_tool: transient error POSTing run-session "
                f"(graph_id={graph_id}), attempt {attempt}/{POST_MAX_ATTEMPTS}: "
                f"{type(e).__name__}: {e}. Retrying in {backoff:.1f}s."
            )
            time.sleep(backoff)
            continue
        except httpx.HTTPError as e:
            # Non-transient httpx error (e.g. a timeout) -- fail immediately,
            # matching the previous no-retry behavior for these cases.
            return None, (
                f"could not reach the EpicStaff API to start sub-flow "
                f"(graph_id={graph_id}): {str(e)[:300]}"
            )

        if response.status_code >= 500:
            if attempt >= POST_MAX_ATTEMPTS:
                return None, (
                    f"failed to start sub-flow (graph_id={graph_id}) -- gave up "
                    f"after {attempt} attempt(s), server kept returning "
                    f"{response.status_code}: {response.text[:300]}"
                )
            backoff = POST_BACKOFF_BASE_S * (2 ** (attempt - 1))
            logger.warning(
                f"fanout_tool: server error ({response.status_code}) starting "
                f"sub-flow (graph_id={graph_id}), attempt {attempt}/"
                f"{POST_MAX_ATTEMPTS}. Retrying in {backoff:.1f}s."
            )
            time.sleep(backoff)
            continue

        return response, None


def _poll_get_session(client, base_url, headers, session_id):
    """
    GET /sessions/<id>/ for use inside the poll loop. Unlike
    `_get_session_or_raise` (used by the recursion guard, where any failure
    must be fatal), this distinguishes a *transient* failure from a fatal
    one so `_poll_until_terminal` can retry the former and abort on the
    latter.

    Returns (session_data, error) where exactly one is None. `error` is a
    tuple (is_transient: bool, message: str).
    """
    import httpx

    try:
        response = client.get(f"{base_url}/sessions/{session_id}/", headers=headers)
    except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as e:
        return None, (True, f"{type(e).__name__}: {e}")
    except httpx.HTTPError as e:
        return None, (False, f"{str(e)[:300]}")

    if response.status_code >= 500:
        return None, (True, f"status {response.status_code}: {response.text[:300]}")

    if response.status_code != 200:
        return None, (
            False,
            f"could not read session {session_id} (status "
            f"{response.status_code}): {response.text[:300]}",
        )

    return response.json(), None


def _poll_until_terminal(
    client, base_url, headers, sub_session_id, graph_id, deadline, poll_timeout_s
):
    """
    Poll GET /sessions/<id>/ until a terminal status is reached, the overall
    `poll_timeout_s` deadline passes, or too many *consecutive* transient
    errors happen in a row (MAX_CONSECUTIVE_POLL_ERRORS).

    A single transient error (RemoteProtocolError / ConnectError / ReadError
    / 5xx) does NOT abort the poll -- it's logged and retried with backoff,
    since the sub-flow is very likely still running server-side. The
    consecutive-error counter resets on every successful poll, so only a
    truly-dead server (repeated failures back to back) terminates the item
    early.

    Returns (session_data, status, error_message): error_message is None on
    success (a terminal status was reached).
    """
    consecutive_errors = 0

    while True:
        session_data, error = _poll_get_session(client, base_url, headers, sub_session_id)

        if error is not None:
            is_transient, message = error

            if not is_transient:
                return None, None, (
                    f"could not reach the EpicStaff API while polling sub-flow "
                    f"session {sub_session_id} (graph_id={graph_id}): {message}"
                )

            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                return None, None, (
                    f"lost contact with the EpicStaff API while polling sub-flow "
                    f"session {sub_session_id} (graph_id={graph_id}) -- gave up "
                    f"after {consecutive_errors} consecutive transient connection "
                    f"errors ({message}). This looks like a transient server "
                    f"disconnect (e.g. 'server disconnected without sending a "
                    f"response'), not a sub-flow failure -- the sub-flow itself "
                    f"may still be running."
                )

            backoff = min(
                POLL_INTERVAL_S * (2 ** (consecutive_errors - 1)),
                MAX_POLL_ERROR_BACKOFF_S,
            )
            logger.warning(
                f"fanout_tool: transient error polling sub-flow session "
                f"{sub_session_id} (graph_id={graph_id}), consecutive failure "
                f"{consecutive_errors}/{MAX_CONSECUTIVE_POLL_ERRORS}: {message}. "
                f"Retrying in {backoff:.1f}s -- treating this as a transient "
                f"disconnect, not a sub-flow failure."
            )

            if time.monotonic() >= deadline:
                return None, None, (
                    f"sub-flow session {sub_session_id} (graph_id={graph_id}) did "
                    f"not finish within {poll_timeout_s}s (last state: transient "
                    f"connection errors while polling, not a confirmed failure)."
                )

            time.sleep(backoff)
            continue

        consecutive_errors = 0
        status = session_data.get("status")
        if status in TERMINAL_STATUSES:
            return session_data, status, None

        if time.monotonic() >= deadline:
            return None, None, (
                f"sub-flow session {sub_session_id} (graph_id={graph_id}) did not "
                f"finish within {poll_timeout_s}s (last status: '{status}')."
            )

        time.sleep(POLL_INTERVAL_S)


def _run_subflow_and_wait(client, base_url, headers, graph_id, variables, poll_timeout_s, parent_session_id):
    """
    Start a single saved flow (graph_id) as a sub-flow, poll it to
    completion and return its output. Never raises.

    Mirrors subflow_tool.main()'s run+poll logic (minus the graph_id/api_key
    presence checks and the recursion guard, which are the caller's
    responsibility here since they only need to run once per fan-out call,
    not once per child), plus the transient-error retry/pooling described in
    the module docstring.

    `client` is the single pooled httpx.Client shared across the whole
    fan-out call (see `_new_http_client`) -- reused here for both the
    initial POST and every poll GET instead of opening a fresh connection
    per request.

    Returns a 3-tuple:
        (True, output_variables: dict, child_session_id) on success
        (False, error_message: str, None) on failure
    """
    try:
        payload = {"graph_id": graph_id, "variables": variables}
        if parent_session_id is not None:
            payload["parent_session_id"] = parent_session_id

        start_response, post_error = _post_run_session_with_retry(
            client, base_url, headers, payload, graph_id
        )
        if post_error:
            return False, post_error, None

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
        session_data, status, poll_error = _poll_until_terminal(
            client, base_url, headers, sub_session_id, graph_id, deadline, poll_timeout_s
        )
        if poll_error:
            return False, poll_error, None

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

    # One pooled client, shared for the recursion check and every POST/poll
    # made by every worker below — see `_new_http_client`.
    with _new_http_client(workers) as client:
        # Recursion guard runs once — every item targets the same graph_id
        # and links to the same caller session, so a single ancestor-chain
        # walk covers all of them.
        if current_session_id is not None:
            try:
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

        if runnable_indices:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(
                        _run_subflow_and_wait,
                        client,
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

    # One pooled client, shared across every stage's recursion check, POST
    # and poll — see `_new_http_client`. Stages run strictly sequentially so
    # a small pool is enough; the size only needs to comfortably cover one
    # in-flight request at a time.
    with _new_http_client(pool_size=2) as client:
        for idx, gid in enumerate(graph_ids):
            if not gid:
                return f"Error: graph_ids[{idx}] is missing or invalid."

            if link_session_id is not None:
                try:
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
                client, base_url, headers, gid, stage_input, poll_timeout_s, link_session_id
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
