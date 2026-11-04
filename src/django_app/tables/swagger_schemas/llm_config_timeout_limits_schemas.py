from tables.serializers.model_serializers.llm_serializers import (
    LLMConfigTimeoutLimitsSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

LLM_CONFIG_TIMEOUT_LIMITS_GET = {
    "summary": "Get LLM config timeout limits",
    "description": (
        "Returns the deployment-wide limits, in seconds, that an LLM config's timeout "
        "is validated against. The same for every organization."
    ),
    "responses": {
        200: LLMConfigTimeoutLimitsSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
    },
}
