from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.serializers.execution_timeout_limits_serializers import (
    ExecutionTimeoutLimitsSerializer,
)
from tables.swagger_schemas.execution_timeout_limits_schemas import (
    EXECUTION_TIMEOUT_LIMITS_GET,
)


class ExecutionTimeoutLimitsAPIView(APIView):
    """Deployment-wide execution timeout limits the flow editor validates against.

    Not org-scoped: the limits come from deployment configuration and are the same
    for every organization, so any authenticated user may read them.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(**EXECUTION_TIMEOUT_LIMITS_GET)
    def get(self, request):
        serializer = ExecutionTimeoutLimitsSerializer(
            {
                "min_seconds": settings.MIN_EXECUTION_TIMEOUT_SECONDS,
                "default_seconds": settings.DEFAULT_EXECUTION_TIMEOUT_SECONDS,
                "max_seconds": settings.MAX_EXECUTION_TIMEOUT_SECONDS,
            }
        )
        return Response(serializer.data)
