from drf_spectacular.utils import OpenApiResponse, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE
from tables.serializers.default_config_serializers import (
    DefaultModelsSerializer,
)


DEFAULT_MODELS_GET = dict(
    summary="Get default models",
    description="Returns the current default models configuration.",
    responses={
        200: DefaultModelsSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Not found",
            examples=[
                OpenApiExample(
                    "Not found",
                    value={"detail": "Not found."},
                    response_only=True,
                ),
            ],
        ),
    },
)

DEFAULT_MODELS_PUT = dict(
    summary="Update default models",
    description="Updates the default models configuration with the provided values.",
    responses={
        200: DefaultModelsSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation Error",
            examples=[
                OpenApiExample(
                    "Validation error",
                    value={"field": ["This field is required."]},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Not found",
            examples=[
                OpenApiExample(
                    "Not found",
                    value={"detail": "Not found."},
                    response_only=True,
                ),
            ],
        ),
    },
)

ENVIRONMENT_CONFIG_GET = dict(
    summary="Retrieve environment configuration",
    description="Returns the current environment configuration as a key-value map.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Config retrieved successfully",
            examples=[
                OpenApiExample(
                    "Config retrieved",
                    value={"data": {"SOME_KEY": "some_value"}},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

ENVIRONMENT_CONFIG_POST = dict(
    summary="Create or update environment configuration ",
    description="Creates or updates one or more environment configuration key-value pairs.",
    responses={
        201: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Config updated successfully",
            examples=[
                OpenApiExample(
                    "Config updated",
                    value={"data": {"SOME_KEY": "some_value"}},
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid config data provided",
            examples=[
                OpenApiExample(
                    "Invalid data",
                    value={"data": ["This field is required."]},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

ENVIRONMENT_CONFIG_DELETE = dict(
    summary="Delete an environment configuration key",
    description="Removes a specific key from the environment configuration.",
    responses={
        204: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Config deleted successfully",
            examples=[
                OpenApiExample(
                    "Config deleted",
                    value="Config deleted successfully",
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="No key provided",
            examples=[
                OpenApiExample(
                    "No key provided",
                    value="No key provided",
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Key not found",
            examples=[
                OpenApiExample(
                    "Key not found",
                    value="Key not found",
                    response_only=True,
                ),
            ],
        ),
    },
)

QUICKSTART_GET = dict(
    summary="Get quickstart status",
    description="Returns the list of supported LLM providers, the last applied quickstart configuration, and whether the current setup is synced.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="List of supported providers",
            examples=[
                OpenApiExample(
                    "Quickstart status",
                    value={
                        "supported_providers": ["openai", "anthropic"],
                        "last_config": {"config_name": "openai_config"},
                        "is_synced": True,
                    },
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Failed to retrieve quickstart status",
            examples=[
                OpenApiExample(
                    "Internal server error",
                    value={"detail": "Failed to retrieve quickstart status"},
                    response_only=True,
                ),
            ],
        ),
    },
)

QUICKSTART_POST = dict(
    summary="Initiate quickstart",
    description="Initiates the quickstart process for a specified provider, creating default configurations and resources as needed.",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Quickstart initiated successfully",
            examples=[
                OpenApiExample(
                    "Quickstart success",
                    value={
                        "detail": "Quickstart initiated successfully!",
                        "config_name": "openai_config",
                        "configs": {
                            "config_name": "openai_config",
                            "llm_config": {},
                            "embedding_config": {},
                            "realtime_config": {},
                            "realtime_transcription_config": {},
                        },
                    },
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid input or quickstart error",
            examples=[
                OpenApiExample(
                    "Quickstart error",
                    value={"detail": "Error quickstart", "error": "Invalid API key"},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

QUICKSTART_APPLY_POST = dict(
    summary="Apply quickstart configuration",
    description="Applies the quickstart configuration to the system, activating any new settings or resources created during the quickstart process.",
    responses={
        200: DefaultModelsSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="No quickstart config found",
            examples=[
                OpenApiExample(
                    "No quickstart config",
                    value={
                        "detail": "No quickstart config found. Run POST /quickstart/ first."
                    },
                    response_only=True,
                ),
            ],
        ),
    },
)
