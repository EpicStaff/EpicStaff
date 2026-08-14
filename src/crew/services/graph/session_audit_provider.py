import asyncio
from functools import lru_cache

from cachetools import TTLCache
from loguru import logger

from settings import AUDIT_TRAIL_ENABLED, AUDITOR_INGEST_API_KEY, AUDITOR_URL
from src.shared.audit import AuditClient, SessionAuditWriter
from src.shared.models import SessionAuditEvent

# session_id -> org_id. Crew-only plumbing: SessionData carries org_id once,
# at the top of run_session, but individual node handlers deep in the call
# graph only have session_id. Not part of the shared SessionAuditWriter -
# that class owns no per-caller state (see shared/audit/session_audit_writer.py).
# TTLCache, not a plain dict, as defensive insurance against a future
# refactor accidentally skipping clear_session_org on some exit path - every
# current exit path already clears it correctly, this is a backstop, not
# the primary mechanism.
_org_id_by_session: TTLCache = TTLCache(maxsize=10_000, ttl=3600)


def register_session_org(session_id: int, org_id: int) -> None:
    _org_id_by_session[session_id] = org_id


def get_session_org(session_id: int) -> int | None:
    return _org_id_by_session.get(session_id)


def clear_session_org(session_id: int) -> None:
    _org_id_by_session.pop(session_id, None)


@lru_cache(maxsize=1)
def get_session_audit_writer() -> SessionAuditWriter:
    """
    Process-wide singleton, built lazily on first use. lru_cache (not a
    manual None-check) for thread-safety - crew itself is single-threaded
    asyncio so this specific race can't occur here, but the pattern is
    shared with django_app's provider (session_audit_provider.py in
    django_app), which genuinely needs it under multi-threaded gunicorn
    workers - keeping both providers identical avoids a footgun if either
    is ever copy-pasted into a new context.
    """
    client: AuditClient[SessionAuditEvent] = AuditClient(
        base_url=AUDITOR_URL,
        ingest_path="/api/audit/events",
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
        logger.warning(f"Audit task failed, event dropped: {exc}")


def track_audit_task(coro) -> None:
    task = asyncio.create_task(coro)
    _audit_tasks.add(task)
    task.add_done_callback(_on_audit_task_done)


def emit_session_audit_event(data: dict) -> None:
    """
    Dispatches one custom-stream-shaped message dict into the audit pipeline.
    Reusable from any call site that already publishes `data` onto
    "graph:messages" (the main run_session astream loop, and any subgraph
    node that has to publish directly - see classification_decision_table_node.py's
    _publish_message and decision_table_node.py's, both of which bypass the
    parent graph's astream because subgraph StreamWriter chunks don't
    propagate to it).

    `data` must already carry a "uuid" - the same id used as the primary
    pipeline's dedup/identity key, reused here as the audit event id.

    Never blocks the primary pipeline - fire-and-forget via create_task,
    except add_start_message which is cache-only and synchronous.
    """
    session_id = data.get("session_id")
    org_id = get_session_org(session_id) if session_id is not None else None
    if org_id is None:
        return

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
                node_name=node_name,
                node_type=node_type,
                execution_order=execution_order,
                input_=message_data.get("input") or {},
                event_id=event_id,
            )
        )
    elif message_type == "finish":
        track_audit_task(
            writer.add_finish_message(
                session_id=session_id,
                org_id=org_id,
                node_name=node_name,
                node_type=node_type,
                execution_order=execution_order,
                output=message_data.get("output") or {},
                event_id=event_id,
                additional_data=message_data.get("additional_data"),
            )
        )
    elif message_type == "error":
        # Real ErrorMessageData serializes to "details"; the chunk-cleaning
        # exception fallback (a few lines up in run_session) uses "error"
        # instead - handle both since they're both real shapes in this file.
        error_detail = (
            message_data.get("details") or message_data.get("error") or "unknown error"
        )
        track_audit_task(
            writer.add_error_message(
                session_id=session_id,
                org_id=org_id,
                node_name=node_name,
                node_type=node_type,
                execution_order=execution_order,
                error=error_detail,
                event_id=event_id,
            )
        )
    else:
        track_audit_task(
            writer.add_custom_message(
                session_id=session_id,
                org_id=org_id,
                node_name=node_name,
                execution_order=execution_order,
                message_data=message_data,
                event_id=event_id,
            )
        )
