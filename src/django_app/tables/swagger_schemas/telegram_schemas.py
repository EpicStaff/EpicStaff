from drf_spectacular.utils import OpenApiResponse, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

TELEGRAM_TRIGGER_AVAILABLE_FIELDS_GET = dict(
    summary="Get available fields for TelegramTriggerNode",
    description="Returns all possible fields that can be created for a TelegramTriggerNode.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="List of available fields returned successfully.",
            examples=[
                OpenApiExample(
                    "Available fields",
                    value={"data": ["field_1", "field_2", "field_3"]},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)
