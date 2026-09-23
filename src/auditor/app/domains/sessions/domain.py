from app.domains.base import DEFAULT_SCOPING, ApiSpec, AuditDomain
from app.domains.sessions.computed import SESSIONS_COMPUTED
from app.domains.sessions.docs import (
    SEARCH_REQUEST_EXAMPLES,
    SEARCH_SESSIONS_DESCRIPTION,
)
from app.domains.sessions.expansion import SessionTreeExpander
from app.domains.sessions.fields import SESSIONS_FIELDS
from app.domains.sessions.index import SESSIONS_INDEX
from app.domains.sessions.schemas import (
    SessionExportRequest,
    SessionSearchRequest,
    SessionSearchResponse,
)
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
    api=ApiSpec(
        search_request_model=SessionSearchRequest,
        search_response_model=SessionSearchResponse,
        export_request_model=SessionExportRequest,
        search_description=SEARCH_SESSIONS_DESCRIPTION,
        search_examples=SEARCH_REQUEST_EXAMPLES,
    ),
)
