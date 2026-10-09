from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.serializers.recycle_bin_serializers import RecycleBinSettingsSerializer


class RecycleBinSettingsView(APIView):
    """Recycle-bin settings. Global, not per organization, so any signed-in user reads them."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=RecycleBinSettingsSerializer)
    def get(self, request):
        return Response(
            RecycleBinSettingsSerializer(
                {"retention_days": settings.RECYCLE_BIN_RETENTION_DAYS}
            ).data
        )
