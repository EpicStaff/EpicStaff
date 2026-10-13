from tables.serializers.sandbox_limits_serializers import SandboxLimitsSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

SANDBOX_LIMITS_GET = {
    "summary": "Get sandbox limits",
    "description": (
        "Returns the deployment-wide limits that node sandbox settings are validated "
        "against. The same for every organization."
    ),
    "responses": {
        200: SandboxLimitsSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
    },
}
