from typing import Optional

from django.conf import settings

from src.shared.audit import AuditClient, SessionAuditWriter
from src.shared.models import SessionAuditEvent

_session_audit_writer: Optional[SessionAuditWriter] = None


def get_session_audit_writer() -> SessionAuditWriter:
    """Process-wide singleton, built lazily on first use."""
    global _session_audit_writer
    if _session_audit_writer is None:
        client: AuditClient[SessionAuditEvent] = AuditClient(
            base_url=settings.AUDITOR_URL,
            ingest_path="/api/audit/events",
            api_key=settings.AUDITOR_INGEST_API_KEY,
            enabled=settings.AUDIT_TRAIL_ENABLED,
            # django_app has no persistent event loop (register_message runs
            # via asgiref.sync.async_to_sync, a per-call temporary loop) - a
            # background batch task would be abandoned before ever running.
            immediate=True,
        )
        _session_audit_writer = SessionAuditWriter(client)
    return _session_audit_writer