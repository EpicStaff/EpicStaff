from app.domains.base import DEFAULT_SCOPING, AuditDomain
from app.domains.sessions.computed import SESSIONS_COMPUTED
from app.domains.sessions.expansion import SessionTreeExpander
from app.domains.sessions.fields import SESSIONS_FIELDS
from app.domains.sessions.index import SESSIONS_INDEX
from src.shared.models import SessionAuditEvent

SESSIONS = AuditDomain(
    name="sessions",
    event_model=SessionAuditEvent,
    index=SESSIONS_INDEX,
    fields=SESSIONS_FIELDS,
    scoping=DEFAULT_SCOPING,
    computed=SESSIONS_COMPUTED,
    expander=SessionTreeExpander(),
    resource="AUDIT",
)
