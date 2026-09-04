import uuid
from datetime import datetime, timezone
from typing import Any

from cachetools import TTLCache
from loguru import logger

from src.shared.audit.client import AuditClient
from src.shared.audit.writer import derive_root_id, safe_emit
from src.shared.models import SessionAuditEvent

AUDIT_NAMESPACE = uuid.UUID("c6e6a7c0-6b3b-4c2b-9f2e-8e6a2a2b6b3a")


def _as_object(value: Any) -> dict[str, Any] | None:
    """
    crew's own input/output fields (StartMessageData.input, FinishMessageData.
    output) are typed `object` upstream - a node can legitimately finish with
    a bare string/list/number, not just a dict (e.g. a python node's plain
    string result). SessionAuditEvent.input/output must stay dict-shaped
    because OpenSearch's mapping for these fields is `object` - a bare scalar
    would fail to index. Wrap anything non-dict rather than dropping it.
    """
    if value is None or isinstance(value, dict):
        return value
    return {"value": value}


def _derive_node_id(session_id: int, node_name: str, execution_order: int) -> str:
    """
    Deterministic per-node-execution id, computable the moment a node starts
    - not just at finish/error time. This is what makes the start event (and
    any activity event during the node's run) able to set the correct
    parent_id immediately, without waiting for something that's only minted
    once the node is done. Same trick as the session's own derive_root_id,
    one level down: (session_id, node_name, execution_order) uniquely
    identifies one node execution within one session.
    """
    return derive_root_id(AUDIT_NAMESPACE, f"{session_id}:{node_name}:{execution_order}")


class SessionAuditWriter:
    """
    Domain-level writer for the session-audit domain: knows how to translate
    session/node/event vocabulary into a correctly-shaped SessionAuditEvent
    and emit it via the shared AuditClient plumbing.

    Used directly by both crew (node lifecycle, session end) and django_app
    (HITL messages) - each caller supplies its own org_id and mints its own
    event ids; this class owns no per-caller/per-service state beyond the
    start-input cache, which exists so the eventual "Finish"/"Error" event
    can carry the node's input too.

    Both nodes and sessions follow the same write-once/append-only shape
    (audit_events is never edited - see _emit_node_or_event's docstring):
    a `kind="node"`/`kind="session"` wrapper doc is written once, early,
    with `status=None` forever - pure identity/parent, never touched again.
    The real outcome always lives on a separate `kind="event"` row instead
    ("Finish"/"Error" for nodes, "Session End" for sessions), written once,
    at completion. This is what survives a crash between start and finish:
    the wrapper already exists, even if the outcome event never arrives.

    Every message type beyond start/finish/error (python, llm, agent,
    agent_finish, user, task, update_session_status, condition_group,
    condition_group_manipulation, classification_prompt, subgraph_start,
    subgraph_finish - see crew/models/graph_models.py) is supplementary
    detail about a node's execution, not a top-level input/output/error -
    all of them route through add_custom_message, which stores the caller's
    dict as-is in `details`.
    """

    def __init__(self, client: AuditClient[SessionAuditEvent]):
        self._client = client
        self._start_cache: TTLCache = TTLCache(maxsize=5000, ttl=3600)

    async def add_start_message(
        self,
        *,
        session_id: int,
        org_id: int,
        node_name: str,
        execution_order: int,
        input_: dict,
        event_id: str,
        node_type: str = "",
    ) -> None:
        """
        Writes two immutable records, once, at node start - mirrors
        add_session_start one level down, same reasoning: audit_events is
        write-once/append-only (no edits, ever), so if the process crashes
        between start and finish/error, we need a real record to already
        exist - not a promise to fill one in later.

        1. The kind="node" wrapper doc, id=_derive_node_id(...). Pure
           identity - org_id, session_id, name, node_type only. status stays
           None forever; the real outcome lives on the "Finish"/"Error"
           event instead (add_finish_message/add_error_message), never here.
        2. A kind="event" "Start" row, parented to that wrapper - carries the
           node's actual input, since that's already known at this point.
        """
        self._start_cache[(session_id, node_name, execution_order)] = input_
        node_audit_id = _derive_node_id(session_id, node_name, execution_order)
        session_parent_id = derive_root_id(AUDIT_NAMESPACE, str(session_id))

        wrapper = SessionAuditEvent(
            id=node_audit_id,
            org_id=org_id,
            kind="node",
            parent_id=session_parent_id,
            session_id=session_id,
            name=node_name,
            node_type=node_type,
            status=None,
            event_time=datetime.now(timezone.utc),
        )
        await safe_emit(self._client, wrapper)

        await self._emit_node_or_event(
            id=event_id,
            parent_id=node_audit_id,
            session_id=session_id,
            org_id=org_id,
            kind="event",
            status="completed",
            name=node_name,
            node_type=node_type,
            input_=input_,
            details={"message_type": "start"},
        )

    def _pop_start_input(
        self, session_id: int, node_name: str, execution_order: int
    ) -> dict | None:
        """
        A miss here (TTL expiry past 1h, or maxsize=5000 eviction under high
        concurrency) means this node's finish/error event silently loses its
        input - logged so that loss is visible instead of silent, not fixed
        outright (the alternative, an unbounded cache, is worse).
        """
        key = (session_id, node_name, execution_order)
        if key not in self._start_cache:
            logger.warning(
                f"No cached start input for session={session_id} node={node_name} "
                f"execution_order={execution_order} - TTL expiry or cache eviction; "
                "this node's audit event will have input=None."
            )
            return None
        return self._start_cache.pop(key)

    async def add_finish_message(
        self,
        *,
        session_id: int,
        org_id: int,
        node_name: str,
        execution_order: int,
        output: dict,
        event_id: str,
        node_type: str = "",
        additional_data: dict | None = None,
    ) -> None:
        """
        Writes the "Finish" kind="event" row - the node's actual outcome.
        The kind="node" wrapper's own status stays None forever (see
        add_start_message); this event is the only place a node's real
        completion state ever lives, mirroring add_session_end one level up.
        """
        input_ = self._pop_start_input(session_id, node_name, execution_order)
        node_audit_id = _derive_node_id(session_id, node_name, execution_order)
        await self._emit_node_or_event(
            id=event_id,
            parent_id=node_audit_id,
            session_id=session_id,
            org_id=org_id,
            kind="event",
            status="completed",
            name=node_name,
            node_type=node_type,
            input_=input_,
            output=output,
            details={**(additional_data or {}), "message_type": "finish"},
        )

    async def add_error_message(
        self,
        *,
        session_id: int,
        org_id: int,
        node_name: str,
        execution_order: int,
        error: Exception | str,
        event_id: str,
        node_type: str = "",
    ) -> None:
        """
        Writes the "Error" kind="event" row - the node's actual outcome on
        failure. Same reasoning as add_finish_message: the kind="node"
        wrapper's own status stays None forever, this event is the only
        place a node's real completion state ever lives. error is
        stringified but otherwise passed through flat, matching the primary
        pipeline's ErrorMessageData.details (also a plain str(error)).
        """
        input_ = self._pop_start_input(session_id, node_name, execution_order)
        node_audit_id = _derive_node_id(session_id, node_name, execution_order)
        await self._emit_node_or_event(
            id=event_id,
            parent_id=node_audit_id,
            session_id=session_id,
            org_id=org_id,
            kind="event",
            status="failed",
            name=node_name,
            node_type=node_type,
            input_=input_,
            error=str(error),
            details={"message_type": "error"},
        )

    async def add_custom_message(
        self,
        *,
        session_id: int,
        org_id: int,
        node_name: str,
        execution_order: int,
        message_data: dict,
        event_id: str,
    ) -> None:
        """
        kind='event' rows - every message type other than start/finish/error
        (python, llm, agent, condition_group, subgraph_start/finish, django_app's
        HITL register_message, etc.) lands here, verbatim in `details`.
        Callable directly by any service, not just crew. Parented to the same
        deterministic node id as the start event - execution_order is what
        makes that possible without waiting for the node's outcome row.
        """
        node_audit_id = _derive_node_id(session_id, node_name, execution_order)
        await self._emit_node_or_event(
            id=event_id,
            parent_id=node_audit_id,
            session_id=session_id,
            org_id=org_id,
            kind="event",
            status="completed",
            name=node_name,
            details=message_data,
        )

    async def _emit_node_or_event(
        self,
        *,
        id: str,
        parent_id: str,
        session_id: int,
        org_id: int,
        kind: str,
        status: str,
        name: str,
        node_type: str = "",
        session_message_id: str | None = None,
        input_: dict | None = None,
        output: dict | None = None,
        error: str | None = None,
        details: dict | None = None,
    ) -> None:
        """
        id/parent_id are always supplied by the caller now, never derived
        here - node-level rows/events parent to the node's deterministic id
        (_derive_node_id), session-level ones parent to the session's
        (derive_root_id(session_id)); the two are no longer interchangeable
        the way a single internal derivation could imply.
        """
        event = SessionAuditEvent(
            id=id,
            org_id=org_id,
            kind=kind,
            parent_id=parent_id,
            session_id=session_id,
            session_message_id=session_message_id if session_message_id is not None else id,
            name=name,
            node_type=node_type,
            status=status,
            event_time=datetime.now(timezone.utc),
            input=_as_object(input_),
            output=_as_object(output),
            error=error,
            details=details or {},
        )
        await safe_emit(self._client, event)

    async def add_session_start(
        self,
        *,
        session_id: int,
        org_id: int,
        flow_name: str,
        event_id: str,
        run_type: str = "",
    ) -> None:
        """
        Writes two immutable records, once, at the top of run_session - never
        touched again (hard rule: audit_events is write-once/append-only, no
        edits, ever):

        1. The kind="session" identity doc, id=derive_root_id(session_id).
           Pure wrapper/parent for everything else in this session - org_id,
           session_id, flow_name only. status stays None forever on this
           document; it is never the source of truth for whether/how a
           session completed (see add_session_end).
        2. A kind="event" "Session Start" row, parented to that identity doc -
           the trace-timeline marker, mirroring the node-level start-event
           pattern one level up. Carries details.message_type="session_start"
           for the same reason node-level events carry message_type="start" -
           a machine-readable marker independent of `name`, which is
           otherwise a free-form/display field elsewhere (see
           duration_filter.py in auditor, which pairs these markers to
           compute duration and must never rely on `name` for that).
        """
        session_audit_id = derive_root_id(AUDIT_NAMESPACE, str(session_id))
        identity_event = SessionAuditEvent(
            id=session_audit_id,
            org_id=org_id,
            kind="session",
            parent_id="",
            session_id=session_id,
            flow_name=flow_name,
            run_type=run_type,
            status=None,
            event_time=datetime.now(timezone.utc),
        )
        await safe_emit(self._client, identity_event)
        await self._emit_node_or_event(
            id=event_id,
            parent_id=session_audit_id,
            session_id=session_id,
            org_id=org_id,
            kind="event",
            status="completed",
            name="Session Start",
            details={"message_type": "session_start"},
        )

    async def add_session_end(
        self,
        *,
        session_id: int,
        org_id: int,
        event_id: str,
        status: str,
        session_message_id: str | None = None,
        output: dict | None = None,
        details: dict | None = None,
        run_type: str = "",
    ) -> None:
        """
        Writes the "Session End" kind="event" row - this is the only place a
        session's actual completion state (status/output/details) ever
        lives; the kind="session" identity doc's own status stays None
        forever (see add_session_start). event_id: reuse the real
        GraphSessionMessage.uuid where one exists (the graph_end message on
        the happy path); mint a fresh uuid for StopSession/timeout/generic
        exception paths, which never publish a GraphMessage at all.
        Carries details.message_type="session_end" - see add_session_start's
        docstring for why this exists alongside `name`.
        """
        parent_id = derive_root_id(AUDIT_NAMESPACE, str(session_id))
        event = SessionAuditEvent(
            id=event_id,
            org_id=org_id,
            kind="event",
            parent_id=parent_id,
            session_id=session_id,
            session_message_id=session_message_id or event_id,
            name="Session End",
            run_type=run_type,
            status=status,
            event_time=datetime.now(timezone.utc),
            output=_as_object(output),
            details={**(details or {}), "message_type": "session_end"},
        )
        await safe_emit(self._client, event)

    async def shutdown(self) -> None:
        """Delegates to the underlying AuditClient's best-effort drain-and-flush."""
        await self._client.shutdown()
