from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.exceptions import (
    FlowWithTriggerNodesRequiresRunPermissionError,
    TriggerNodesRequireRunPermissionError,
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

TRIGGER_NODES_REQUIRE_RUN_403_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description=(
        "The request would create or edit a trigger node (webhook, Telegram, schedule) "
        "and the caller lacks RUN on flows; nothing was written. Also returned as the "
        "standard `permission_denied` 403 when the caller lacks the endpoint's own permission."
    ),
    examples=[
        OpenApiExample(
            "Trigger nodes require Run",
            value={
                "status_code": 403,
                "code": TriggerNodesRequireRunPermissionError.default_code,
                "message": TriggerNodesRequireRunPermissionError.default_detail,
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
        "the caller lacks RUN on flows; nothing was written. Also returned as the standard "
        "`permission_denied` 403 when the caller lacks the endpoint's own permission."
    ),
    examples=[
        OpenApiExample(
            "Flow with trigger nodes requires Run",
            value={
                "status_code": 403,
                "code": FlowWithTriggerNodesRequiresRunPermissionError.default_code,
                "message": FlowWithTriggerNodesRequiresRunPermissionError.default_detail,
            },
            response_only=True,
            status_codes=["403"],
        ),
    ],
)
