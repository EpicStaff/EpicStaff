# Wait-For-Decision Tool
#
# EST-3285 4.8 human-in-the-loop, part (a): a SESSION-LEVEL, REST-POLLING
# design -- deliberately NOT the crewAI task-level `human_input=True` ->
# `get_wait_for_user_callback` -> `sessions:{id}:user_input` Redis pub/sub
# mechanism (session_callback_factory.py). That mechanism runs IN-PROCESS
# inside the crew container and cannot be reused here: built-in python-code
# tools (this one included) execute OUT-OF-PROCESS in the sandbox, and only
# talk to django_app over plain REST -- exactly like subflow_tool talks to
# `/run-session/` + `/sessions/<id>/`. This tool copies that same
# open-then-poll pattern against three new session-scoped endpoints:
#
#   POST /sessions/<session_id>/decisions/open/    -- opens the decision,
#       sets Session.status = wait_for_user, publishes a
#       "wait_for_decision" GraphSessionMessage for the frontend.
#   GET  /sessions/<session_id>/                   -- (existing endpoint)
#       polled for status_data.decision.answer.
#   POST /sessions/<session_id>/decisions/cancel/   -- called ONLY if this
#       tool's own bounded poll times out, to reset the session back to
#       'run' and clear the stale decision so it doesn't stay wedged in
#       wait_for_user forever.
#
# The crew naturally pauses here for the SAME reason subflow_tool naturally
# pauses a flow while its sub-flow runs: this tool's `main()` call blocks
# (polling) until the answer arrives (or it times out) -- the agent step
# that invoked this tool simply doesn't return until then. No change to
# get_wait_for_user_callback, AnswerToLLM, or the node-level
# human_input=True path is needed or made.
#
# TIMEOUT / TTL NOTE: a session sitting in wait_for_user still burns its
# normal `Session.time_to_live` TTL exactly as it always has (unrelated
# infra, unchanged here). This tool's own `poll_timeout_s` is a SEPARATE,
# tool-level bound (default DEFAULT_POLL_TIMEOUT_S below) that should be
# configured well under the session's time_to_live; on timeout the tool
# calls the cancel endpoint so the session resumes to 'run' rather than
# silently expiring while still nominally "waiting".
#
# `session_id` is injected as a bare module global by the crew engine for
# every built-in python-code tool call (see `global_kwargs["session_id"]` in
# src/crew/services/graph/nodes/crew_node.py) -- this tool cannot pause a
# session it wasn't told about, and never accepts session_id as an agent
# argument (mirrors schedule_manager_tool's graph_id-is-config-only /
# session_id-is-injected-only ownership pattern: the agent can never target
# a DIFFERENT session's decision).

import time

try:
    from loguru import logger
except ImportError:  # pragma: no cover - sandbox venv without loguru installed

    class _NoOpLogger:
        def warning(self, *args, **kwargs):
            pass

    logger = _NoOpLogger()

DEFAULT_API_BASE_URL = "http://djangoapp:8000/api"
DEFAULT_POLL_TIMEOUT_S = 900
POLL_INTERVAL_S = 3.0
HTTP_TIMEOUT_S = 15.0
MIN_OPTIONS = 2
MAX_OPTIONS = 4


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


def _cancel_decision(client, base_url: str, headers: dict, session_id, decision_id) -> str:
    """Best-effort cleanup call on timeout. Never raises -- returns a
    readable note either way, appended to the timeout error message."""
    import httpx

    try:
        response = client.post(
            f"{base_url}/sessions/{session_id}/decisions/cancel/",
            json={"decision_id": decision_id},
            headers=headers,
        )
        if response.status_code == 200:
            return "The session has been resumed (decision request cancelled)."
        return (
            f"(warning: could not cancel the pending decision cleanly, status "
            f"{response.status_code} -- session may remain paused until it "
            f"expires via its normal time_to_live)"
        )
    except httpx.HTTPError:
        return (
            "(warning: could not reach the API to cancel the pending decision "
            "-- session may remain paused until it expires via its normal "
            "time_to_live)"
        )


def _format_answer(decision: dict, options: list) -> str:
    answer = decision.get("answer") or {}
    option_index = answer.get("option_index")
    free_text = answer.get("free_text")

    parts = []
    if option_index is not None and isinstance(option_index, int) and 0 <= option_index < len(options):
        parts.append(f"User selected option {option_index}: '{options[option_index]}'.")
    if free_text:
        parts.append(f"Additional free-text input: '{free_text}'.")

    if not parts:
        return "User responded, but no option or free text could be parsed from the answer."
    return " ".join(parts)


def main(
    question: str | None = None,
    options: list | None = None,
    allow_free_text: bool | None = True,
    **kwargs,
) -> str:
    """
    Pause the flow and ask a human to pick one of 2-4 options (optionally
    with free text) for the given session, then block (polling) until an
    answer is recorded or a bounded timeout is hit. Never raises: all
    failures are returned as readable error strings.
    """
    try:
        import httpx

        session_id = globals().get("session_id")
        api_key = globals().get("api_key")
        poll_timeout_s = globals().get("poll_timeout_s")
        if poll_timeout_s is None:
            poll_timeout_s = DEFAULT_POLL_TIMEOUT_S

        if session_id is None:
            # Non-fatal degradation, surfaced rather than silently no-op'd:
            # this tool can only pause a LIVE flow session; there is nothing
            # to poll for outside a running session context.
            return (
                "Error: no session_id available -- this tool can only pause a "
                "live flow session; it cannot be used outside a running "
                "session context."
            )
        if not api_key:
            return (
                "Error: 'api_key' is missing. Configure an EpicStaff API key "
                "for this tool before using the Wait-For-Decision Tool."
            )
        if not question or not isinstance(question, str):
            return "Error: 'question' is required and must be a non-empty string."
        if not isinstance(options, list) or not (MIN_OPTIONS <= len(options) <= MAX_OPTIONS):
            return (
                f"Error: 'options' must be a list of {MIN_OPTIONS}-{MAX_OPTIONS} "
                "strings."
            )
        if not all(isinstance(o, str) and o for o in options):
            return "Error: every entry in 'options' must be a non-empty string."

        base_url = _api_base_url()
        headers = _headers(api_key)
        open_payload = {
            "question": question,
            "options": options,
            "allow_free_text": bool(allow_free_text),
        }

        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                open_response = client.post(
                    f"{base_url}/sessions/{session_id}/decisions/open/",
                    json=open_payload,
                    headers=headers,
                )
        except httpx.HTTPError as e:
            return (
                "Error: could not reach the EpicStaff API to open the "
                f"decision: {str(e)[:300]}"
            )

        if open_response.status_code not in (200, 201):
            return (
                f"Error: failed to open decision for session {session_id}, "
                f"status {open_response.status_code}: {open_response.text[:300]}"
            )

        try:
            decision_id = open_response.json()["decision_id"]
        except (ValueError, KeyError) as e:
            return f"Error: unexpected response opening decision: {e}"

        deadline = time.monotonic() + poll_timeout_s

        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_S) as client:
                while True:
                    get_response = client.get(
                        f"{base_url}/sessions/{session_id}/", headers=headers
                    )
                    if get_response.status_code != 200:
                        return (
                            f"Error: could not poll session {session_id} "
                            f"(status {get_response.status_code}): "
                            f"{get_response.text[:300]}"
                        )

                    session_data = get_response.json()
                    decision = (session_data.get("status_data") or {}).get(
                        "decision"
                    ) or {}

                    if (
                        decision.get("decision_id") == decision_id
                        and decision.get("answer") is not None
                    ):
                        return _format_answer(decision, options)

                    if time.monotonic() >= deadline:
                        cancel_note = _cancel_decision(
                            client, base_url, headers, session_id, decision_id
                        )
                        return (
                            f"Error: no decision received within "
                            f"{poll_timeout_s}s for question '{question}'. "
                            f"{cancel_note}"
                        )

                    time.sleep(POLL_INTERVAL_S)
        except httpx.HTTPError as e:
            return (
                f"Error: network failure while polling for a decision on "
                f"session {session_id}: {str(e)[:300]}"
            )
    except Exception as e:
        return f"Error: wait_for_decision tool failed. Unexpected exception: {e}"
