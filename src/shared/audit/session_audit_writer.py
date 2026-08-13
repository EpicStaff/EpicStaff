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


class SessionAuditWriter:
    """
    Domain-level writer for the session-audit domain: knows how to translate
    session/node/event vocabulary into a correctly-shaped SessionAuditEvent
    and emit it via the shared AuditClient plumbing.

    Used directly by both crew (node lifecycle, session end) and django_app
    (HITL messages) - each caller supplies its own org_id and mints its own
    event ids; this class owns no per-caller/per-service state beyond the
    start-input cache, which is a rule about SessionAuditEvent's own shape
    (no "running" status exists) rather than anything crew-specific.

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

    def add_start_message(
        self, session_id: int, node_name: str, execution_order: int, input_: dict
    ) -> None:
        """No row emitted yet - cached until the matching finish/error resolves it."""
        self._start_cache[(session_id, node_name, execution_order)] = input_

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
        additional_data: dict | None = None,
    ) -> None:
        input_ = self._pop_start_input(session_id, node_name, execution_order)
        await self._emit_node_or_event(
            session_id=session_id,
            org_id=org_id,
            event_id=event_id,
            kind="node",
            status="completed",
            name=node_name,
            input_=input_,
            output=output,
            details=additional_data,
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
    ) -> None:
        """
        error is stringified but otherwise passed through flat, matching the
        primary pipeline's ErrorMessageData.details (also a plain str(error)).
        """
        input_ = self._pop_start_input(session_id, node_name, execution_order)
        await self._emit_node_or_event(
            session_id=session_id,
            org_id=org_id,
            event_id=event_id,
            kind="node",
            status="failed",
            name=node_name,
            input_=input_,
            error=str(error),
        )

    async def add_custom_message(
        self,
        *,
        session_id: int,
        org_id: int,
        node_name: str,
        message_data: dict,
        event_id: str,
    ) -> None:
        """
        kind='event' rows - every message type other than start/finish/error
        (python, llm, agent, condition_group, subgraph_start/finish, django_app's
        HITL register_message, etc.) lands here, verbatim in `details`.
        Callable directly by any service, not just crew.
        """
        await self._emit_node_or_event(
            session_id=session_id,
            org_id=org_id,
            event_id=event_id,
            kind="event",
            status="completed",
            name=node_name,
            details=message_data,
        )

    async def _emit_node_or_event(
        self,
        *,
        session_id: int,
        org_id: int,
        event_id: str,
        kind: str,
        status: str,
        name: str,
        input_: dict | None = None,
        output: dict | None = None,
        error: str | None = None,
        details: dict | None = None,
    ) -> None:
        parent_id = derive_root_id(AUDIT_NAMESPACE, str(session_id))
        event = SessionAuditEvent(
            id=event_id,
            org_id=org_id,
            kind=kind,
            parent_id=parent_id,
            session_id=session_id,
            session_message_id=event_id,
            name=name,
            status=status,
            event_time=datetime.now(timezone.utc),
            input=_as_object(input_),
            output=_as_object(output),
            error=error,
            details=details or {},
        )
        await safe_emit(self._client, event)

    async def add_session_end(
        self,
        *,
        session_id: int,
        org_id: int,
        status: str,
        session_message_id: str | None = None,
        output: dict | None = None,
        flow_name: str | None = None,
        details: dict | None = None,
    ) -> None:
        """
        session_message_id: the real GraphSessionMessage.uuid minted at the
        graph_end call site on the happy path (see graph_session_manager_
        service.py) - None for StopSession/generic exception paths, which
        never publish a GraphMessage at all.
        """
        session_audit_id = derive_root_id(AUDIT_NAMESPACE, str(session_id))
        event = SessionAuditEvent(
            id=session_audit_id,
            org_id=org_id,
            kind="session",
            parent_id="",
            session_id=session_id,
            session_message_id=session_message_id,
            flow_name=flow_name or "",
            status=status,
            event_time=datetime.now(timezone.utc),
            output=_as_object(output),
            details=details or {},
        )
        await safe_emit(self._client, event)

    async def shutdown(self) -> None:
        """Delegates to the underlying AuditClient's best-effort drain-and-flush."""
        await self._client.shutdown()
