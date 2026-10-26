"""SuperAdmin suspend and resume of one organization's grant, and what suspending it stops.

Deployment-wide and JWT-only, like the rest of the plugin admin API: the organization is the
grant's, never the `X-Organization-Id` header.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.lifecycle.suspend_preview_service import SuspendPreviewService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.serializers.admin import PluginGrantSerializer
from plugins.serializers.suspension import SuspendPreviewSerializer
from plugins.views.admin_plugins import ADMIN_AUTHENTICATION, ADMIN_PERMISSIONS, grant_details


class PluginGrantSuspendPreviewView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(responses=SuspendPreviewSerializer)
    def get(self, request, identifier: str, grant_id: int):
        preview = SuspendPreviewService().build(identifier, grant_id)
        return Response(SuspendPreviewSerializer(preview).data)


class PluginGrantSuspendView(APIView):
    """Suspend a grant: its runs, keys and pages stop at once, its data stays for the grace period."""

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(request=None, responses=PluginGrantSerializer)
    def post(self, request, identifier: str, grant_id: int):
        grant = PluginSuspensionService().suspend(identifier, grant_id, request.user)
        return Response(grant_details(grant.pk))


class PluginGrantResumeView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(request=None, responses=PluginGrantSerializer)
    def post(self, request, identifier: str, grant_id: int):
        grant = PluginSuspensionService().resume(identifier, grant_id, request.user)
        return Response(grant_details(grant.pk))
