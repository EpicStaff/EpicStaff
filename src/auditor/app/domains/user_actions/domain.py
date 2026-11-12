from app.domains.base import DEFAULT_SCOPING, ApiSpec, AuditDomain, NullExpander
from app.domains.user_actions.docs import (
    SEARCH_REQUEST_EXAMPLES,
    SEARCH_USER_ACTIONS_DESCRIPTION,
)
from app.domains.user_actions.fields import USER_ACTIONS_FIELDS
from app.domains.user_actions.index import USER_ACTIONS_INDEX
from app.domains.user_actions.schemas import (
    UserActionExportRequest,
    UserActionSearchRequest,
    UserActionSearchResponse,
)
from src.shared.models import UserActionEvent

USER_ACTIONS: AuditDomain[UserActionEvent] = AuditDomain(
    name="user_actions",
    event_model=UserActionEvent,
    index=USER_ACTIONS_INDEX,
    fields=USER_ACTIONS_FIELDS,
    scoping=DEFAULT_SCOPING,
    computed=(),
    expander=NullExpander(),
    resource="USER_AUDIT",
    api=ApiSpec(
        search_request_model=UserActionSearchRequest,
        search_response_model=UserActionSearchResponse,
        export_request_model=UserActionExportRequest,
        search_description=SEARCH_USER_ACTIONS_DESCRIPTION,
        search_examples=SEARCH_REQUEST_EXAMPLES,
    ),
    value_fields=frozenset({"target_type"}),
)
