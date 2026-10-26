from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.exceptions import (
    FlowWithTriggerNodesRequiresUsePermissionError,
    TriggerNodesRequireUsePermissionError,
)

UNAUTHORIZED_401_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.STR,
    description="Request is not authenticated — credentials are missing or invalid.",
    examples=[
        OpenApiExample(
            "Not authenticated",
            value={
                "status_code": 401,
                "code": "not_authenticated",
                "message": "NotAuthenticated: Authentication credentials were not provided.",
            },
            response_only=True,
            status_codes=["401"],
        ),
    ],
)

# What `custom_exception_handler` renders for an exception it does not
# recognise. The exception's text is never part of it -- it is logged instead.
INTERNAL_SERVER_ERROR_500_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description="Unexpected server error. The cause is logged server-side, never returned.",
    examples=[
        OpenApiExample(
            "Server error",
            value={
                "status_code": 500,
                "code": "OperationalError",
                "message": "Unpredictable error",
            },
            response_only=True,
            status_codes=["500"],
        ),
    ],
)

TRIGGER_NODES_REQUIRE_USE_403_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description=(
        "The request would create or edit a trigger node (webhook, Telegram, schedule) "
        "and the caller lacks USE on flows; nothing was written. Also returned as the "
        "standard `permission_denied` 403 when the caller lacks the endpoint's own permission."
    ),
    examples=[
        OpenApiExample(
            "Trigger nodes require Use",
            value={
                "status_code": 403,
                "code": TriggerNodesRequireUsePermissionError.default_code,
                "message": TriggerNodesRequireUsePermissionError.default_detail,
            },
            response_only=True,
            status_codes=["403"],
        ),
    ],
)

FLOW_WITH_TRIGGER_NODES_403_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description=(
        "The flow, file or snapshot holds a trigger node (webhook, Telegram, schedule) and "
        "the caller lacks USE on flows; nothing was written. Also returned as the standard "
        "`permission_denied` 403 when the caller lacks the endpoint's own permission."
    ),
    examples=[
        OpenApiExample(
            "Flow with trigger nodes requires Use",
            value={
                "status_code": 403,
                "code": FlowWithTriggerNodesRequiresUsePermissionError.default_code,
                "message": FlowWithTriggerNodesRequiresUsePermissionError.default_detail,
            },
            response_only=True,
            status_codes=["403"],
        ),
    ],
)
