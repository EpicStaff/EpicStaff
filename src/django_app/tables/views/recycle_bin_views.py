from django.conf import settings
from drf_spectacular.utils import extend_schema
from rbac.access.gates import DenyApiKeyAuth
from rbac.access.resolver import PermissionResolver
from rbac.scoping.mixins import OrgScopedResolverMixin
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.serializers.recycle_bin_serializers import (
    RecycleBinEmptyResponseSerializer,
    RecycleBinSettingsSerializer,
)
from tables.services.recycle_bin.empty_service import RecycleBinEmptyService
from tables.views.recycle_bin_mixins import request_actor


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
    """Empty the active organization's recycle bin: every type the caller may see and delete.

    One request per slice instead of one per type: each call purges for a limited time and
    says how many items remain, and the client calls again. Types the caller can't delete
    are left alone, the same tabs the bin page offers; each item is its own transaction,
    and a failed one is reported, not raised. The bin's most destructive call, so API keys can't make it: a
    leaked key must not wipe a whole organization's bin.
    """

    permission_classes = [IsAuthenticated, DenyApiKeyAuth]

    @extend_schema(request=None, responses=RecycleBinEmptyResponseSerializer)
    def post(self, request):
        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(user=request.user, org_id=org_id)
        sources = RecycleBinEmptyService.purgeable_sources(effective)
        if not sources:
            raise PermissionDenied("You can't delete anything in this recycle bin.")
        result = RecycleBinEmptyService.empty(
            org_id=org_id, sources=sources, actor=request_actor(request)
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
