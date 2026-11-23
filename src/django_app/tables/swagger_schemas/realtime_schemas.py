from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE, error_example

INIT_REALTIME_POST = {
    "summary": "Initialize a realtime agent session",
    "description": (
        "Initializes a realtime agent session for a `RealtimeAgentDefinition` "
        "(pass `agent_definition_id`)."
    ),
    "responses": {
        201: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Realtime agent created successfully",
            examples=[
                OpenApiExample(
                    "Realtime agent created",
                    value={"connection_key": "abc123xyz"},
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request - Invalid Input",
            examples=[
                OpenApiExample(
                    "Validation error",
                    value=error_example(
                        "required", "This field is required.", "agent_definition_id"
                    ),
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}
