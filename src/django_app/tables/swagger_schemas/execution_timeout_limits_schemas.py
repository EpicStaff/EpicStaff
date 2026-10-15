from tables.serializers.execution_timeout_limits_serializers import (
    ExecutionTimeoutLimitsSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

EXECUTION_TIMEOUT_LIMITS_GET = {
    "summary": "Get execution timeout limits",
    "description": (
        "Returns the deployment-wide limits, in seconds, that a python code's "
        "execution_timeout is validated against. The same for every organization."
    ),
    "responses": {
        200: ExecutionTimeoutLimitsSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
    },
}
