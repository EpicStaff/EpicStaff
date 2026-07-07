# Schedule Manager Tool
#
# Creates/lists/updates/deletes cron-style scheduled (recurring or one-off)
# triggers for a single saved EpicStaff flow (graph), via the EXISTING
# `/api/schedule-trigger-nodes/` REST endpoint (a full ModelViewSet over
# ScheduleTriggerNode — see tables/views/model_view_sets.py). No new Django
# model, migration, or node type is introduced: this tool only drives the
# already-shipped schedule-trigger-node CRUD surface over HTTP, exactly the
# way subflow_tool drives `/run-session/` + `/sessions/<id>/`.
#
# `graph_id`, `api_key` and `api_base_url` are NOT function parameters: they
# are declared in args_schema.json with "input_type": "user_input", so they
# are seeded as tool CONFIG variables (set once when the tool is configured
# for an agent) rather than agent-callable arguments. The sandbox executor
# injects configured values as module-level globals before this function
# runs — see `globals().get(...)` below.
#
# Ownership boundary: `graph_id` is fixed at tool-configuration time and is
# never accepted from the agent. Every action is scoped to that one graph:
#   - 'list' always filters `?graph=<graph_id>`.
#   - 'create' always sends `graph=<graph_id>` and never lets the agent
#     choose a different target graph.
#   - 'update'/'delete' first GET the schedule by id and refuse to proceed
#     if its `graph` field does not match the configured graph_id, so this
#     tool instance can never read/modify/delete another graph's (and, by
#     extension, another organization's) schedules even though schedule ids
#     are plain integers. This mirrors subflow_tool's graph_id-is-config-only
#     pattern; there is currently no Organization-level scoping on
#     /schedule-trigger-nodes/ or /run-session/ in the wider system, so
#     graph_id pinning is the strongest ownership boundary available today.
#
# Jitter: recurring schedules whose start_date_time lands exactly on a round
# clock boundary (seconds == 0 and minute is a multiple of 30 -- i.e. :00 or
# :30) are nudged by a small random offset (1..jitter_seconds_max-1 seconds,
# default < 45s) before being sent, so many schedules created around the
# same "nice" time don't all fire in the same instant. This is applied
# entirely client-side to `start_date_time`: the model has no separate
# jitter field, and `next_run_date_time` is always derived server-side (by
# ScheduleTriggerService) from `start_date_time` + interval, so offsetting
# start_date_time is sufficient and needs no other change.

import json
import random
import secrets
from datetime import datetime, timedelta

try:
    from loguru import logger
except ImportError:  # pragma: no cover - sandbox venv without loguru installed

    class _NoOpLogger:
        def warning(self, *args, **kwargs):
            pass

    logger = _NoOpLogger()

DEFAULT_API_BASE_URL = "http://djangoapp:8000/api"
HTTP_TIMEOUT_S = 15.0
DEFAULT_JITTER_SECONDS_MAX = 45
LIST_RESULT_CAP = 100
VALID_ACTIONS = {"create", "list", "update", "delete"}
VALID_RUN_MODES = {"once", "repeat"}
VALID_UNITS = {"seconds", "minutes", "hours", "days", "weeks", "months"}
VALID_END_TYPES = {"never", "on_date", "after_n_runs"}


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


def _maybe_jitter_start(start_date_time, apply_jitter: bool, jitter_max: int):
    """Return (possibly-offset start_date_time, applied_offset_seconds|None)."""
    if not apply_jitter or not start_date_time:
        return start_date_time, None
    try:
        dt = datetime.fromisoformat(str(start_date_time).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return start_date_time, None

    if dt.second != 0 or dt.microsecond != 0:
        return start_date_time, None
    if dt.minute % 30 != 0:
        return start_date_time, None

    jitter_max = max(2, int(jitter_max))
    offset = random.randint(1, jitter_max - 1)
    jittered = dt + timedelta(seconds=offset)
    return jittered.isoformat(), offset


def _fetch_node(client, base_url: str, headers: dict, schedule_id):
    response = client.get(
        f"{base_url}/schedule-trigger-nodes/{schedule_id}/", headers=headers
    )
    if response.status_code == 404:
        return None, None
    if response.status_code != 200:
        return None, (
            f"Error: could not read schedule {schedule_id} "
            f"(status {response.status_code}): {response.text[:300]}"
        )
    return response.json(), None


def _check_ownership(node: dict, graph_id) -> str | None:
    if node.get("graph") != graph_id:
        return (
            f"Error: schedule {node.get('id')} belongs to graph "
            f"{node.get('graph')}, not the graph this tool is configured for "
            f"(graph_id={graph_id}). Refusing to access another graph's schedule."
        )
    return None


def _build_schedule_block(baseline: dict, args: dict, apply_jitter: bool, jitter_max: int):
    """Merge `baseline` (an existing node's rendered `schedule` block, or {}
    for a brand-new schedule) with agent-supplied overrides in `args`, and
    return (schedule_dict, jitter_offset_seconds|None, error|None).

    Always produces a *complete* schedule block (run_mode/timezone/
    start_date_time/interval/end all populated) rather than a partial patch,
    so the server-side validator (which requires every/unit to travel
    together, end_date_time/max_runs to match end_type, etc.) always sees an
    internally consistent state regardless of which single field the agent
    meant to change.
    """
    baseline_interval = baseline.get("interval") or {}
    baseline_end = baseline.get("end") or {}

    run_mode = args.get("run_mode", baseline.get("run_mode"))
    if run_mode not in VALID_RUN_MODES:
        return None, None, (
            f"Error: 'run_mode' must be one of {sorted(VALID_RUN_MODES)} "
            f"(got {run_mode!r})."
        )

    timezone_name = args.get("timezone", baseline.get("timezone")) or "UTC"
    start_date_time = args.get("start_date_time", baseline.get("start_date_time"))
    if not start_date_time:
        return None, None, "Error: 'start_date_time' is required."

    jittered_start, jitter_offset = _maybe_jitter_start(
        start_date_time, apply_jitter, jitter_max
    )

    every = args.get("every", baseline_interval.get("every"))
    unit = args.get("unit", baseline_interval.get("unit"))
    weekdays = args.get("weekdays", baseline_interval.get("weekdays"))

    if run_mode == "repeat":
        if every is None or unit is None:
            return None, None, (
                "Error: run_mode='repeat' requires both 'every' and 'unit' "
                "(supply both together, not just one)."
            )
        if unit not in VALID_UNITS:
            return None, None, f"Error: 'unit' must be one of {sorted(VALID_UNITS)}."
        interval_block = {"every": every, "unit": unit, "weekdays": weekdays or []}
    else:
        interval_block = {"every": None, "unit": None, "weekdays": None}

    end_type = args.get("end_type", baseline_end.get("type")) or "never"
    if end_type not in VALID_END_TYPES:
        return None, None, f"Error: 'end_type' must be one of {sorted(VALID_END_TYPES)}."

    end_date_time = args.get("end_date_time", baseline_end.get("date_time"))
    max_runs = args.get("max_runs", baseline_end.get("max_runs"))

    if end_type == "on_date" and not end_date_time:
        return None, None, "Error: end_type='on_date' requires 'end_date_time'."
    if end_type == "after_n_runs" and not max_runs:
        return None, None, "Error: end_type='after_n_runs' requires 'max_runs'."
    if end_type == "never":
        end_date_time = None
        max_runs = None

    schedule_block = {
        "run_mode": run_mode,
        "timezone": timezone_name,
        "start_date_time": jittered_start,
        "interval": interval_block,
        "end": {"type": end_type, "date_time": end_date_time, "max_runs": max_runs},
    }
    return schedule_block, jitter_offset, None


def _do_create(client, base_url, headers, graph_id, args):
    schedule_block, jitter_offset, error = _build_schedule_block(
        {},
        args,
        args.get("apply_jitter", True),
        args.get("jitter_seconds_max", DEFAULT_JITTER_SECONDS_MAX),
    )
    if error:
        return error

    node_name = args.get("node_name") or f"agent_schedule_{secrets.token_hex(4)}"
    is_active = args.get("is_active", True)

    payload = {
        "graph": graph_id,
        "node_name": node_name,
        "is_active": is_active,
        "schedule": schedule_block,
    }

    response = client.post(
        f"{base_url}/schedule-trigger-nodes/", json=payload, headers=headers
    )
    if response.status_code not in (200, 201):
        return (
            f"Error: failed to create schedule (graph_id={graph_id}), status "
            f"{response.status_code}: {response.text[:300]}"
        )

    result = response.json()
    note = (
        f" (start_date_time jittered by +{jitter_offset}s to avoid herding)"
        if jitter_offset
        else ""
    )
    return json.dumps({"created": result, "note": note.strip() or None})


def _do_list(client, base_url, headers, graph_id, args):
    params = {"graph": graph_id}
    if "is_active" in args and args.get("is_active") is not None:
        params["is_active"] = args["is_active"]

    response = client.get(
        f"{base_url}/schedule-trigger-nodes/", params=params, headers=headers
    )
    if response.status_code != 200:
        return (
            f"Error: failed to list schedules (graph_id={graph_id}), status "
            f"{response.status_code}: {response.text[:300]}"
        )

    body = response.json()
    results = body.get("results") if isinstance(body, dict) else body
    results = results or []

    truncated = len(results) > LIST_RESULT_CAP
    if truncated:
        results = results[:LIST_RESULT_CAP]

    return json.dumps(
        {
            "graph_id": graph_id,
            "count_returned": len(results),
            "truncated": truncated,
            "schedules": results,
        }
    )


def _do_update(client, base_url, headers, graph_id, args):
    schedule_id = args.get("schedule_id")
    if not schedule_id:
        return "Error: 'schedule_id' is required for action='update'."

    node, error = _fetch_node(client, base_url, headers, schedule_id)
    if error:
        return error
    if node is None:
        return f"Error: schedule {schedule_id} not found."

    ownership_error = _check_ownership(node, graph_id)
    if ownership_error:
        return ownership_error

    schedule_fields_supplied = any(
        key in args
        for key in (
            "run_mode",
            "start_date_time",
            "timezone",
            "every",
            "unit",
            "weekdays",
            "end_type",
            "end_date_time",
            "max_runs",
        )
    )

    payload = {}
    if "node_name" in args and args["node_name"]:
        payload["node_name"] = args["node_name"]
    if "is_active" in args and args["is_active"] is not None:
        payload["is_active"] = args["is_active"]

    jitter_offset = None
    if schedule_fields_supplied:
        schedule_block, jitter_offset, error = _build_schedule_block(
            node.get("schedule") or {},
            args,
            args.get("apply_jitter", True),
            args.get("jitter_seconds_max", DEFAULT_JITTER_SECONDS_MAX),
        )
        if error:
            return error
        payload["schedule"] = schedule_block

    if not payload:
        return "Error: no fields supplied to update."

    response = client.patch(
        f"{base_url}/schedule-trigger-nodes/{schedule_id}/",
        json=payload,
        headers=headers,
    )
    if response.status_code not in (200,):
        return (
            f"Error: failed to update schedule {schedule_id}, status "
            f"{response.status_code}: {response.text[:300]}"
        )

    result = response.json()
    note = (
        f" (start_date_time jittered by +{jitter_offset}s to avoid herding)"
        if jitter_offset
        else ""
    )
    return json.dumps({"updated": result, "note": note.strip() or None})


def _do_delete(client, base_url, headers, graph_id, args):
    schedule_id = args.get("schedule_id")
    if not schedule_id:
        return "Error: 'schedule_id' is required for action='delete'."

    node, error = _fetch_node(client, base_url, headers, schedule_id)
    if error:
        return error
    if node is None:
        return f"Error: schedule {schedule_id} not found."

    ownership_error = _check_ownership(node, graph_id)
    if ownership_error:
        return ownership_error

    response = client.delete(
        f"{base_url}/schedule-trigger-nodes/{schedule_id}/", headers=headers
    )
    if response.status_code not in (200, 202, 204):
        return (
            f"Error: failed to delete schedule {schedule_id}, status "
            f"{response.status_code}: {response.text[:300]}"
        )

    return json.dumps({"deleted": schedule_id})


def main(
    action: str | None = None,
    schedule_id: int | None = None,
    node_name: str | None = None,
    run_mode: str | None = None,
    start_date_time: str | None = None,
    timezone: str | None = None,
    every: int | None = None,
    unit: str | None = None,
    weekdays: list | None = None,
    end_type: str | None = None,
    end_date_time: str | None = None,
    max_runs: int | None = None,
    is_active: bool | None = None,
    apply_jitter: bool | None = None,
    jitter_seconds_max: int | None = None,
    **kwargs,
) -> str:
    """
    Create/list/update/delete a scheduled (cron-style) trigger for the graph
    this tool is configured for. Never raises: all failures are returned as
    readable error strings.
    """
    try:
        import httpx

        graph_id = globals().get("graph_id")
        api_key = globals().get("api_key")

        if not graph_id:
            return (
                "Error: 'graph_id' is missing. Configure which saved flow this "
                "tool manages schedules for before using the Schedule Manager Tool."
            )
        if not api_key:
            return (
                "Error: 'api_key' is missing. Configure an EpicStaff API key for "
                "this tool before using the Schedule Manager Tool."
            )

        if action not in VALID_ACTIONS:
            return f"Error: 'action' must be one of {sorted(VALID_ACTIONS)} (got {action!r})."

        args = {
            "schedule_id": schedule_id,
            "node_name": node_name,
            "run_mode": run_mode,
            "start_date_time": start_date_time,
            "timezone": timezone,
            "every": every,
            "unit": unit,
            "weekdays": weekdays,
            "end_type": end_type,
            "end_date_time": end_date_time,
            "max_runs": max_runs,
            "is_active": is_active,
            "apply_jitter": True if apply_jitter is None else apply_jitter,
            "jitter_seconds_max": jitter_seconds_max
            if jitter_seconds_max is not None
            else DEFAULT_JITTER_SECONDS_MAX,
        }
        # Drop keys the caller never supplied (None) so `key in args` checks
        # in the update path reflect "was this explicitly requested".
        args = {k: v for k, v in args.items() if v is not None}

        base_url = _api_base_url()
        headers = _headers(api_key)

        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                if action == "create":
                    return _do_create(client, base_url, headers, graph_id, args)
                if action == "list":
                    return _do_list(client, base_url, headers, graph_id, args)
                if action == "update":
                    return _do_update(client, base_url, headers, graph_id, args)
                return _do_delete(client, base_url, headers, graph_id, args)
        except httpx.HTTPError as e:
            return (
                "Error: could not reach the EpicStaff API for the schedule "
                f"manager tool: {str(e)[:300]}"
            )
    except Exception as e:
        return f"Error: schedule manager tool failed. Unexpected exception: {e}"
