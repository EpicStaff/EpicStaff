from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.serializers.sandbox_limits_serializers import SandboxLimitsSerializer
from tables.swagger_schemas.sandbox_limits_schemas import SANDBOX_LIMITS_GET


class SandboxLimitsAPIView(APIView):
    """Deployment-wide sandbox limits the flow editor validates node settings against.

    Not org-scoped: the limits come from deployment configuration and are the same
    for every organization, so any authenticated user may read them.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(**SANDBOX_LIMITS_GET)
    def get(self, request):
        serializer = SandboxLimitsSerializer(
            {"max_execution_timeout_minutes": settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES}
        )
        return Response(serializer.data)
