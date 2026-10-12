import json
from datetime import datetime

from tables.import_export.export_tabular_projections.base import TabularProjection

_STREAM_TYPES = {"task_node_stream", "agent_node_stream"}
_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "cached_prompt_tokens", "total_tokens")
# `state` is the whole variable namespace and can be huge.
_DROPPED_KEYS = {"message_type", "state"}
_EMPTY_VALUES = (None, "", {}, [])
_STARTED_BY_TYPES = {
    "user": "user",
    "api_key_user": "api_key",
    "api_key_system": "system_api_key",
    "trigger": "trigger",
}


def _encode(value):
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _timing_key(message: dict) -> tuple[bool, tuple] | None:
    """Return (is_start, key) pairing a start row with its finish row, or None."""
    data = message.get("message_data") or {}
    message_type = data.get("message_type")
    if message_type in ("start", "finish"):
        return message_type == "start", ("node", message["name"], message["execution_order"])
    if message_type in ("subgraph_start", "subgraph_finish"):
        return message_type == "subgraph_start", ("subgraph", data.get("subgraph_execution_id"))
    return None


def _durations_ms(messages: list[dict]) -> dict[int, int]:
    """Map each finish / subgraph_finish message id to the ms since its start message."""
    # Two passes: a start and its finish can share created_at, so row order can't be trusted.
    started_at = {}
    finishes = []
    for message in messages:
        timing = _timing_key(message)
        if timing is None:
            continue
        is_start, key = timing
        if is_start:
            started_at[key] = datetime.fromisoformat(message["created_at"])
        else:
            finishes.append((message, key))
    return {
        message["id"]: round(
            (datetime.fromisoformat(message["created_at"]) - started_at[key]).total_seconds() * 1000
        )
        for message, key in finishes
        if key in started_at
    }


def _cost(value: float | None) -> str | None:
    if value is None:
        return None
    # Fixed decimal: float sums like 1.4999999999999999e-05 must read as 0.000015.
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _token_columns(usage: dict | None) -> dict:
    usage = usage or {}
    return {
        **{field: usage.get(field) for field in _TOKEN_FIELDS},
        "cost_usd": _cost(usage.get("total_cost_usd")),
    }


def _stream_columns(rest: dict) -> tuple[dict, dict]:
    event = rest.pop("event", None)
    payload = dict(rest.pop("data", None) or {})
    task = payload.pop("task", None) or {}
    columns = {
        "event": event,
        "task_name": task.get("name"),
        **_token_columns(payload.pop("token_usage", None)),
    }
    if event in ("tool_call", "tool_result"):
        columns["tool_name"] = payload.pop("name", None)
    if event == "tool_call":
        columns["tool_arguments"] = payload.pop("arguments", None)
    elif event == "tool_result":
        columns["tool_result"] = payload.pop("content", None)
        if payload.get("is_error"):
            columns["error"] = columns["tool_result"]
    elif event == "task_finish":
        columns["output"] = payload.pop("message", None)
        for field in ("stop_reason", "iterations", "tool_invocations"):
            columns[field] = payload.pop(field, None)
    return columns, {**rest, **payload}


def _finish_columns(rest: dict) -> tuple[dict, dict]:
    output = rest.pop("output", None)
    # Task and Agent nodes return the agent-service result; every other node its own output.
    if not (isinstance(output, dict) and {"stop_reason", "token_usage"} <= output.keys()):
        return {"output": output}, rest
    output = dict(output)
    structured_output = output.pop("structured_output", None)
    columns = {
        "output": structured_output
        if structured_output is not None
        else output.pop("message", None),
        **{
            field: output.pop(field, None)
            for field in ("stop_reason", "iterations", "tool_invocations")
        },
        **_token_columns(output.pop("token_usage", None)),
    }
    return columns, {**rest, **output}


def _python_columns(rest: dict) -> tuple[dict, dict]:
    execution = dict(rest.pop("python_code_execution_data", None) or {})
    columns = {"output": execution.pop("result_data", None)}
    if execution.get("returncode") not in (0, None):
        columns["error"] = execution.pop("stderr", None)
    return columns, {**rest, **execution}


def _message_columns(message_type: str | None, data: dict) -> tuple[dict, dict]:
    """Split message_data into mapped columns and the leftover keys that go to `details`."""
    rest = dict(data)
    if message_type is None:
        return {"output": rest}, {}
    if message_type in _STREAM_TYPES:
        return _stream_columns(rest)
    if message_type == "finish":
        return _finish_columns(rest)
    if message_type == "python":
        return _python_columns(rest)
    if message_type in ("start", "subgraph_start"):
        return {"input": rest.pop("input", None)}, rest
    if message_type == "subgraph_finish":
        return {"output": rest.pop("output", None)}, rest
    if message_type == "extracted_chunks":
        return {"input": rest.pop("knowledge_query", None), "error": rest.pop("error", None)}, rest
    if message_type == "classification_prompt":
        return {
            "input": rest.pop("prompt_text", None),
            # raw_response is a Python repr of the parsed dict, not JSON.
            "output": rest.pop("parsed_result", None),
            **_token_columns(rest.pop("usage", None)),
        }, rest
    if message_type == "error":
        return {"error": rest.pop("details", None) or rest.pop("error", None)}, rest
    if message_type == "python_stream":
        return {"output": rest.pop("text", None)}, rest
    if message_type == "graph_end":
        return {"output": rest.pop("end_node_result", None)}, rest
    return {}, rest


def _started_by(session: dict) -> tuple[str, str | None]:
    principal = session.get("principal") or {}
    started_by_type = _STARTED_BY_TYPES.get(principal.get("kind"), "unknown")
    email = principal.get("email")
    if started_by_type == "user":
        return started_by_type, email
    if started_by_type == "trigger":
        return started_by_type, session.get("trigger_node_name")
    if started_by_type in ("api_key", "system_api_key"):
        # api_key_name is None once the key is deleted (the FK is SET_NULL).
        key_name = principal.get("api_key_name")
        if key_name and email:
            return started_by_type, f"{key_name} ({email})"
        return started_by_type, key_name or email
    return started_by_type, None


def _copy_key(row: dict) -> tuple:
    message_type = (row.get("message_data") or {}).get("message_type")
    return row["created_at"], row["name"], row["execution_order"], message_type


def _node_key(message: dict) -> tuple:
    # A subflow node may share its name with a parent node; the subflow path tells them apart.
    execution_ids = (message.get("message_data") or {}).get("subgraph_execution_ids") or []
    return message["name"], tuple(execution_ids)


class SessionTabularProjection(TabularProjection):
    """One CSV row per GraphSessionMessage.

    Token columns repeat across rows: `task_finish` repeats the per-task usage that the
    node's `finish` row already totals, and `tool_call` / `tool_result` carry deltas.
    Sum only `finish` and `classification_prompt` rows to get token totals. A subflow's
    inner rows live in the parent session and are copied into its child session; copies
    whose original is in the same export are dropped, so each message is counted once.
    A child exported without its parent keeps its copies; fan-out children keep all rows.
    """

    FIELDS = [
        "session_id",
        "flow_id",
        "flow_name",
        "session_status",
        "started_by_type",
        "started_by",
        "message_id",
        "created_at",
        "execution_order",
        "node_name",
        "node_type",
        "message_type",
        "event",
        "task_name",
        "input",
        "output",
        "error",
        "tool_name",
        "tool_arguments",
        "tool_result",
        "stop_reason",
        "iterations",
        "tool_invocations",
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "total_tokens",
        "cost_usd",
        "duration_ms",
        "details",
    ]

    def project(self, row: dict) -> dict:
        data = row.get("message_data") or {}
        message_type = data.get("message_type")
        columns, rest = _message_columns(message_type, data)
        details = {
            key: value
            for key, value in rest.items()
            if key not in _DROPPED_KEYS and value not in _EMPTY_VALUES
        }
        projected = {
            "session_id": row["session_id"],
            "flow_id": row["flow_id"],
            "flow_name": row["flow_name"],
            "session_status": row["session_status"],
            "started_by_type": row["started_by_type"],
            "started_by": row["started_by"],
            "message_id": row["id"],
            "created_at": row["created_at"],
            "execution_order": row["execution_order"],
            "node_name": row["name"],
            "node_type": row["node_type"],
            # The End node writes its mapped output as message_data, with no message_type.
            "message_type": message_type or "end_output",
            "duration_ms": row["duration_ms"],
            **columns,
            "details": details or None,
        }
        return {key: _encode(value) for key, value in projected.items()}

    def expand_all(self, items: list[dict]) -> list[dict]:
        # Subflow inner rows are written to the parent session, then copied into the child
        # session after the parent finishes, so the copy always sits in a later session id.
        # Dedupe on the copied fields across sessions only; fan-out children are separate
        # runs whose rows exist only in the child, so nothing of theirs matches.
        ordered = sorted(items, key=lambda item: (item.get("session") or {}).get("id") or 0)
        seen = set()
        rows = []
        for item in ordered:
            session_rows = self.expand(item)
            rows.extend(row for row in session_rows if _copy_key(row) not in seen)
            seen.update(_copy_key(row) for row in session_rows)
        return rows

    def expand(self, item: dict) -> list[dict]:
        session = item.get("session") or {}
        started_by_type, started_by = _started_by(session)
        context = {
            "flow_id": session.get("graph"),
            "flow_name": session.get("graph_name"),
            "session_status": session.get("status"),
            "started_by_type": started_by_type,
            "started_by": started_by,
        }
        messages = item.get("messages", [])
        # Rows from non-BaseNode emitters store no node_type; the same node's start row does.
        stored_types = {
            _node_key(message): message["node_type"]
            for message in messages
            if message.get("node_type")
        }
        # NOTE: node_type is empty when the emitter is not a BaseNode (SubGraphNode, user
        # messages, graph_end, knowledge search) and on rows saved before it was stored.
        # graph_schema covers top-level nodes only, so old subflow inner rows stay empty.
        schema_types = session.get("node_types") or {}
        durations = _durations_ms(messages)
        return [
            {
                **message,
                **context,
                "node_type": (
                    message.get("node_type")
                    or stored_types.get(_node_key(message))
                    or schema_types.get(message["name"])
                    or ""
                ).lower(),
                "duration_ms": durations.get(message["id"]),
            }
            for message in messages
        ]
