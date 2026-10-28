import asyncio
import json
from dataclasses import dataclass
from functools import lru_cache

from loguru import logger
from settings import AUDIT_TRAIL_ENABLED, AUDITOR_INGEST_API_KEY, AUDITOR_URL
from src.shared.audit.client import AuditClient
from src.shared.audit.writers.session_writer import SessionAuditWriter
from src.shared.models import SessionAuditEvent, SessionData


@dataclass(frozen=True)
class SessionAuditContext:
    """What every audit event of one session needs besides the message itself.

    Attributes:
        audit_retention_days: Days auditor keeps the session's events; 0 keeps forever.
    """

    org_id: int
    flow_name: str
    audit_retention_days: int

    @classmethod
    def from_session_data(cls, session_data: SessionData) -> "SessionAuditContext":
        return cls(
            org_id=session_data.org_id,
            flow_name=session_data.graph.name,
            audit_retention_days=session_data.audit_retention_days,
        )


# session_id -> SessionAuditContext. Crew-only plumbing: SessionData carries
# the context once, at the top of run_session, but individual node handlers
# deep in the call graph only have session_id. Not part of the shared
# SessionAuditWriter - that class owns no per-caller state (see
# shared/audit/writers/session_writer.py).
# A plain dict with no expiry or size bound: an entry must live exactly as long
# as its session, however long that runs. run_session clears it in a `finally`,
# so no exit path leaks one. Crew runs every session in one asyncio event loop,
# so the dict is only ever touched from one thread.
_context_by_session: dict[int, SessionAuditContext] = {}


def register_session_audit_context(session_id: int, context: SessionAuditContext) -> None:
    _context_by_session[session_id] = context


def get_session_audit_context(session_id: int) -> SessionAuditContext | None:
    """Return the session's audit context, or None after logging that its events are dropped.

    None means the session is not running: it ended, or was never registered.
    """
    context = _context_by_session.get(session_id)
    if context is None:
        logger.warning(
            "No audit context for session {} (not running: ended or never registered); "
            "dropping its audit event.",
            session_id,
        )
    return context


def clear_session_audit_context(session_id: int) -> None:
    _context_by_session.pop(session_id, None)


@lru_cache(maxsize=1)
def get_session_audit_writer() -> SessionAuditWriter:
    """
    Process-wide singleton, built lazily on first use. lru_cache (not a
    manual None-check) for thread-safety: crew itself is single-threaded
    asyncio so this specific race can't occur here, but the pattern would
    matter under any multi-threaded caller, so it's kept even though it's
    not strictly needed here.
    """
    client: AuditClient[SessionAuditEvent] = AuditClient(
        base_url=AUDITOR_URL,
        ingest_path="/api/audit/sessions/events",
        api_key=AUDITOR_INGEST_API_KEY,
        enabled=AUDIT_TRAIL_ENABLED,
    )
    return SessionAuditWriter(client)


# Fire-and-forget audit emission tasks (add_finish_message, add_session_end,
# etc.) need a strong reference held somewhere for their lifetime - asyncio's
# own docs warn a Task with no reference anywhere is only weakly tracked by
# the loop and can be garbage-collected mid-execution. safe_emit swallows
# exceptions internally, so a GC'd task here would fail with zero log output,
# unlike every other designed failure mode in this feature.
_audit_tasks: set[asyncio.Task] = set()


def _on_audit_task_done(task: asyncio.Task) -> None:
    _audit_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("Audit task failed, event dropped: {}", exc)


def track_audit_task(coro) -> None:
    task = asyncio.create_task(coro)
    _audit_tasks.add(task)
    task.add_done_callback(_on_audit_task_done)


def _value_or_empty_dict(value):
    # Only None means "absent": False, 0 and "" are real node inputs/outputs
    # and must reach the audit trail as-is.
    return {} if value is None else value


def emit_session_audit_event(encoded_message: str) -> None:
    """
    Dispatches one custom-stream-shaped message into the audit pipeline.
    Reusable from any call site that already adds the message to the graph
    message stream (the main run_session astream loop, and any subgraph
    node that has to write directly - see classification_decision_table_node.py's
    _publish_message and decision_table_node.py's, both of which bypass the
    parent graph's astream because subgraph StreamWriter chunks don't
    propagate to it).

    `encoded_message` is the exact JSON appended to the stream. The writer keeps
    what it is given until a later batch flush, and the message dict shares
    values with live flow state, so the audit decodes its own copy here rather
    than holding references a running node may still change. It must already
    carry a "uuid" - the same id used as the primary pipeline's dedup/identity
    key, reused here as the audit event id.

    Never blocks the primary pipeline: every message type, start included,
    is dispatched as a fire-and-forget asyncio task (track_audit_task) that
    only enqueues onto the shared AuditClient's background batch loop.
    """
    if not AUDIT_TRAIL_ENABLED:
        return
    data = json.loads(encoded_message)
    session_id = data.get("session_id")
    if session_id is None:
        return
    context = get_session_audit_context(session_id)
    if context is None:
        return
    org_id = context.org_id
    flow_name = context.flow_name
    retention_days = context.audit_retention_days

    message_data = data.get("message_data") or {}
    message_type = message_data.get("message_type")
    node_name = data.get("name") or ""
    node_type = data.get("node_type") or ""
    execution_order = data.get("execution_order") or 0
    event_id = data["uuid"]
    writer = get_session_audit_writer()

    if message_type == "start":
        track_audit_task(
            writer.add_start_message(
                session_id=session_id,
                org_id=org_id,
                flow_name=flow_name,
                node_name=node_name,
                node_type=node_type,
                execution_order=execution_order,
                input_=_value_or_empty_dict(message_data.get("input")),
                event_id=event_id,
                retention_days=retention_days,
            )
        )
    elif message_type == "finish":
        track_audit_task(
            writer.add_finish_message(
                session_id=session_id,
                org_id=org_id,
                flow_name=flow_name,
                node_name=node_name,
                node_type=node_type,
                execution_order=execution_order,
                output=_value_or_empty_dict(message_data.get("output")),
                event_id=event_id,
                retention_days=retention_days,
                additional_data=message_data.get("additional_data"),
            )
        )
    elif message_type == "error":
        error_detail = message_data.get("details") or "unknown error"
        track_audit_task(
            writer.add_error_message(
                session_id=session_id,
                org_id=org_id,
                flow_name=flow_name,
                node_name=node_name,
                node_type=node_type,
                execution_order=execution_order,
                error=error_detail,
                event_id=event_id,
                retention_days=retention_days,
            )
        )
    else:
        track_audit_task(
            writer.add_custom_message(
                session_id=session_id,
                org_id=org_id,
                flow_name=flow_name,
                node_name=node_name,
                execution_order=execution_order,
                details=message_data,
                event_id=event_id,
                retention_days=retention_days,
            )
        )
