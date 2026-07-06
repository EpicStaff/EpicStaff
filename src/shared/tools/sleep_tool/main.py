# Sleep Tool
#
# Agent self-pacing primitive: sleeps the sandboxed subprocess for a stated
# duration with a stated reason, so a looped agent run can deliberately pause
# (e.g. to wait out a rate-limit window) instead of hammering an API in a
# tight loop. The tool's own return string is what surfaces in the agent's
# message stream in the UI — no crew-side changes are needed for that.
#
# `max_seconds` is NOT a function parameter the agent controls: it is
# declared in args_schema.json with "input_type": "user_input", so it is
# seeded as a tool CONFIG variable (set once when the tool is configured for
# an agent) and injected by the sandbox executor as a module-level global
# before this function runs — see `globals().get("max_seconds")` below. This
# mirrors schedule_manager_tool's graph_id/api_key config-only pattern.
#
# The sandbox (src/sandbox/dynamic_venv_executor_chain.py) currently has no
# per-execution timeout, so a real time.sleep() call here will actually
# block the tool subprocess for the requested duration. To keep this safe by
# construction, the requested `seconds` is always clamped to
# [0, max_seconds] before sleeping, and the response states plainly when
# clamping occurred.

import time

DEFAULT_MAX_SECONDS = 300


def _coerce_positive_number(raw):
    """Returns (float_value_or_None, error_or_None)."""
    if isinstance(raw, bool):
        return None, f"Error: 'seconds' must be a positive number (got {raw!r})."
    if not isinstance(raw, (int, float)):
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            return None, f"Error: 'seconds' must be a positive number (got {raw!r})."
    if raw != raw or raw in (float("inf"), float("-inf")):  # NaN/inf guard
        return None, f"Error: 'seconds' must be a finite positive number (got {raw!r})."
    if raw <= 0:
        return None, f"Error: 'seconds' must be a positive number greater than 0 (got {raw!r})."
    return float(raw), None


def main(
    seconds: float | int | None = None,
    reason: str | None = None,
) -> str:
    """
    Pause execution for `seconds` (clamped to this tool's configured
    `max_seconds` cap) with a stated `reason`. Never raises: all failures are
    returned as readable error strings. On success, returns a confirmation
    string stating the reason and the actual (possibly clamped) duration
    slept.
    """
    try:
        if reason is None or not isinstance(reason, str) or not reason.strip():
            return "Error: 'reason' is required and must be a non-empty string stating why the agent is pausing."

        if seconds is None:
            return "Error: 'seconds' is required and must be a positive number."

        value, error = _coerce_positive_number(seconds)
        if error:
            return error

        max_seconds_raw = globals().get("max_seconds")
        try:
            max_seconds = float(max_seconds_raw) if max_seconds_raw is not None else DEFAULT_MAX_SECONDS
        except (TypeError, ValueError):
            max_seconds = DEFAULT_MAX_SECONDS
        if max_seconds < 0:
            max_seconds = DEFAULT_MAX_SECONDS

        clamped = max(0.0, min(value, max_seconds))
        was_clamped = clamped != value

        time.sleep(clamped)

        reason_clean = reason.strip()
        if was_clamped:
            return (
                f"Paused {clamped:g}s. Reason: {reason_clean}. "
                f"(requested {value:g}s, capped to {max_seconds:g}s)"
            )
        return f"Paused {clamped:g}s. Reason: {reason_clean}."
    except Exception as e:
        return f"Error: sleep tool failed. Unexpected exception: {e}"
