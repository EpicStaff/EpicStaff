from functools import lru_cache

from cachetools import TTLCache

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
