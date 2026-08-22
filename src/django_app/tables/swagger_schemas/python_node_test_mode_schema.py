from drf_spectacular.utils import OpenApiResponse, inline_serializer
from rest_framework import serializers

LAST_TEST_INPUT_SWAGGER = dict(
    summary="Get Last Test Input for Python Node",
    responses={
        200: OpenApiResponse(
            response=inline_serializer(
                name="PythonNodeLastTestInputResponse",
                fields={
                    "detail": serializers.CharField(
                        help_text="Human-readable status message."
                    ),
                    "input": serializers.JSONField(
                        allow_null=True,
                        help_text=(
                            "The input dict from the last successful test run, "
                            "or null when no matching data is found."
                        ),
                    ),
                },
            ),
            description="Result of the lookup — always 200, check 'input' for data.",
        ),
        404: OpenApiResponse(description="PythonNode not found"),
    },
)
