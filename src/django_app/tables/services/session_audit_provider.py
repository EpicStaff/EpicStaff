from functools import lru_cache

from django.conf import settings

from src.shared.audit import AuditClient, SessionAuditWriter
from src.shared.models import SessionAuditEvent


@lru_cache(maxsize=1)
def get_session_audit_writer() -> SessionAuditWriter:
    """
    Process-wide singleton, built lazily on first use. lru_cache (not a
    manual None-check) for thread-safety: gunicorn workers here run with
    GUNICORN_THREADS configured, so two concurrent first-requests really
    could race a plain `if _x is None` check and build two AuditClients.
    """
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
    return SessionAuditWriter(client)
