from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.models.llm_models import (
    LLM_CONFIG_TIMEOUT_MAX_SECONDS,
    LLM_CONFIG_TIMEOUT_MIN_SECONDS,
)
from tables.serializers.llm_config_timeout_limits_serializers import (
    LLMConfigTimeoutLimitsSerializer,
)
from tables.swagger_schemas.llm_config_timeout_limits_schemas import (
    LLM_CONFIG_TIMEOUT_LIMITS_GET,
)


class LLMConfigTimeoutLimitsAPIView(APIView):
    """Deployment-wide LLM config timeout limits the configuration dialogs validate against.

    Not org-scoped: the limits come from deployment configuration and are the same
    for every organization, so any authenticated user may read them.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(**LLM_CONFIG_TIMEOUT_LIMITS_GET)
    def get(self, request):
        serializer = LLMConfigTimeoutLimitsSerializer(
            {
                "min_seconds": LLM_CONFIG_TIMEOUT_MIN_SECONDS,
                "max_seconds": LLM_CONFIG_TIMEOUT_MAX_SECONDS,
            }
        )
        return Response(serializer.data)
