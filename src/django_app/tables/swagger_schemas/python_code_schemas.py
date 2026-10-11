from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.serializers.serializers import RunPythonCodeSerializer

RUN_PYTHON_CODE_POST = {
    "summary": "Run Python Code",
    "description": (
        "Test-runs Python code with the provided variables and returns an execution ID "
        "to track the run. Send exactly one of `target` or `python_code_id`.\n\n"
        "`target` names a code slot of a node in the active organization and runs it "
        "the way a real flow run would, including storage access when the node uses "
        "storage: the graph's attached files plus a writable folder "
        "`test-runs/<type>-<id>/`, reused across test runs of that node.\n\n"
        "`python_code_id` runs the bare code without any node settings such as storage."
    ),
    "request": RunPythonCodeSerializer,
    "examples": [
        OpenApiExample(
            "Run a python node",
            value={"target": {"type": "python_node", "id": 42}, "variables": {"x": 1}},
            request_only=True,
        ),
        OpenApiExample(
            "Run bare code",
            value={"python_code_id": 7, "variables": {"x": 1}},
            request_only=True,
        ),
    ],
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
            description=(
                "Bad Request: both or neither of `target` and `python_code_id`, an unknown "
                "target type, a target or code not found in the active organization, or "
                "code that reads an undeclared secret."
            ),
            examples=[
                OpenApiExample(
                    "Both or neither given",
                    value={
                        "code": "invalid",
                        "message": "Provide exactly one of `target` or `python_code_id`.",
                        "status_code": 400,
                    },
                    response_only=True,
                ),
                OpenApiExample(
                    "Target not found",
                    value={
                        "code": "invalid",
                        "message": 'target: Invalid pk "42" - object does not exist.',
                        "status_code": 400,
                    },
                    response_only=True,
                ),
            ],
        ),
        403: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="The caller lacks Flows update permission in the active organization.",
        ),
    },
}
