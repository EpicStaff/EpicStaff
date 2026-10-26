"""SuperAdmin uninstall, reinstall and deletion of a plugin, and deletion of a grant's data.

Deployment-wide and JWT-only, like the rest of the plugin admin API. The two permanent deletes
(`DELETE` of a plugin, in `admin_plugins`, and of a grant here) carry the phrase their
preview shows, and are refused before anything changes when it differs.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.lifecycle.grant_purge_service import GrantPurgeService
from plugins.lifecycle.plugin_purge_service import PluginPurgeService
from plugins.lifecycle.purge_preview_service import PurgePreviewService
from plugins.lifecycle.uninstall_service import PluginUninstallService
from plugins.serializers.admin import PluginDetailSerializer, PluginGrantSerializer
from plugins.serializers.purge import (
    GrantPurgePreviewSerializer,
    PluginPurgePreviewSerializer,
    VerificationPhraseSerializer,
)
from plugins.views.admin_plugins import (
    ADMIN_AUTHENTICATION,
    ADMIN_PERMISSIONS,
    grant_details,
    plugin_details,
)


class PluginAdminView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS


class PluginUninstallView(PluginAdminView):
    """Take the plugin out of service everywhere; its data is kept for the grace period."""

    @extend_schema(request=None, responses=PluginDetailSerializer)
    def post(self, request, identifier: str):
        PluginUninstallService().uninstall(identifier, request.user)
        return Response(plugin_details(identifier))


class PluginReinstallView(PluginAdminView):
    @extend_schema(request=None, responses=PluginDetailSerializer)
    def post(self, request, identifier: str):
        PluginUninstallService().reinstall(identifier, request.user)
        return Response(plugin_details(identifier))


class PluginPurgePreviewView(PluginAdminView):
    @extend_schema(responses=PluginPurgePreviewSerializer)
    def get(self, request, identifier: str):
        preview = PurgePreviewService().plugin_preview(identifier)
        return Response(PluginPurgePreviewSerializer(preview).data)


class PluginRetryRemovalView(PluginAdminView):
    """Ask the plugin node to try again a removal it reported as failed."""

    @extend_schema(request=None, responses={202: PluginDetailSerializer})
    def post(self, request, identifier: str):
        PluginPurgeService().retry_removal(identifier, request.user)
        return Response(plugin_details(identifier), status=status.HTTP_202_ACCEPTED)


class PluginGrantPurgePreviewView(PluginAdminView):
    @extend_schema(responses=GrantPurgePreviewSerializer)
    def get(self, request, identifier: str, grant_id: int):
        preview = PurgePreviewService().grant_preview(identifier, grant_id)
        return Response(GrantPurgePreviewSerializer(preview).data)


class PluginGrantDetailView(PluginAdminView):
    @extend_schema(request=VerificationPhraseSerializer, responses={202: PluginGrantSerializer})
    def delete(self, request, identifier: str, grant_id: int):
        """Delete the grant's data in its organization now; irreversible, with the phrase."""
        grant = GrantPurgeService().request(identifier, grant_id, request.data, request.user)
        return Response(grant_details(grant.pk), status=status.HTTP_202_ACCEPTED)
