from drf_spectacular.utils import OpenApiResponse, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from tables.serializers.serializers import RunPythonCodeSerializer

RUN_PYTHON_CODE_POST = dict(
    summary="Run Python Code",
    description="Executes a Python code node with the provided variables and returns an execution ID to track the run.",
    request=RunPythonCodeSerializer,
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Python code execution started successfully",
            examples=[
                OpenApiExample(
                    "Execution started",
                    value={"execution_id": "b3f2c9a0-4e7d-4c2f-9a1e-6d2f8c1b7a3e"},
                    response_only=True,
                ),
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad Request",
            examples=[
                OpenApiExample(
                    "Validation error",
                    value={"error": "Invalid input data."},
                    response_only=True,
                ),
            ],
        ),
    },
)
