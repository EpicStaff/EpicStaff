from typing import Optional

from settings import AUDIT_TRAIL_ENABLED, AUDITOR_INGEST_API_KEY, AUDITOR_URL
from src.shared.audit import AuditClient, SessionAuditWriter
from src.shared.models import SessionAuditEvent

# session_id -> org_id. Crew-only plumbing: SessionData carries org_id once,
# at the top of run_session, but individual node handlers deep in the call
# graph only have session_id. Not part of the shared SessionAuditWriter -
# that class owns no per-caller state (see shared/audit/session_audit_writer.py).
_org_id_by_session: dict[int, int] = {}


def register_session_org(session_id: int, org_id: int) -> None:
    _org_id_by_session[session_id] = org_id


def get_session_org(session_id: int) -> Optional[int]:
    return _org_id_by_session.get(session_id)


def clear_session_org(session_id: int) -> None:
    _org_id_by_session.pop(session_id, None)


_session_audit_writer: Optional[SessionAuditWriter] = None


def get_session_audit_writer() -> SessionAuditWriter:
    """Process-wide singleton, built lazily on first use."""
    global _session_audit_writer
    if _session_audit_writer is None:
        client: AuditClient[SessionAuditEvent] = AuditClient(
            base_url=AUDITOR_URL,
            ingest_path="/api/audit/events",
            api_key=AUDITOR_INGEST_API_KEY,
            enabled=AUDIT_TRAIL_ENABLED,
        )
        _session_audit_writer = SessionAuditWriter(client)
    return _session_audit_writer