from django.conf import settings
from drf_spectacular.utils import extend_schema
from rbac.scoping.mixins import OrgScopedResolverMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.serializers.recycle_bin_serializers import (
    RecycleBinEmptyResponseSerializer,
    RecycleBinSettingsSerializer,
)
from tables.services.recycle_bin.empty_service import RecycleBinEmptyService
from tables.views.recycle_bin_mixins import purge_permissions, request_actor


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


class RecycleBinEmptyView(OrgScopedResolverMixin, APIView):
    """Empty the active organization's recycle bin: every type, a slice per request.

    One request per slice instead of one per type: each call purges for a limited time and
    says how many items remain, and the client calls again. Each item is its own
    transaction, and a failed one is reported, not raised. The bin's most destructive
    call, so it has the per-type purges' gates (`purge_permissions`): superadmin only,
    never with an API key. Neither an org admin nor a leaked key may wipe a whole
    organization's bin.
    """

    def get_permissions(self):
        return purge_permissions([])

    @extend_schema(request=None, responses=RecycleBinEmptyResponseSerializer)
    def post(self, request):
        result = RecycleBinEmptyService.empty(
            org_id=self.get_active_org_id(), actor=request_actor(request)
        )
        failed = [
            {
                "source": item.source,
                "id": item.failure.id,
                "name": item.failure.name,
                "message": item.failure.message,
            }
            for item in result.failed
        ]
        return Response(
            RecycleBinEmptyResponseSerializer(
                {
                    "purged_count": result.purged_count,
                    "failed": failed,
                    "remaining": result.remaining,
                }
            ).data
        )
