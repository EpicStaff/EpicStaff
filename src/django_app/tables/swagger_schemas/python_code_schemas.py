from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.serializers.serializers import RunPythonCodeSerializer

RUN_PYTHON_CODE_POST = {
    "summary": "Run Python Code",
    "description": "Executes a Python code node with the provided variables and returns an execution ID to track the run.",
    "request": RunPythonCodeSerializer,
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Python code execution started successfully",
            examples=[
                OpenApiExample(
                    "Execution started",
                    value={"execution_id": "17-07-2026_19-01-11-924@e66d"},
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
}
