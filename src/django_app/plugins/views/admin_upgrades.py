"""SuperAdmin actions on a plugin's upgrade: cancel, retry, and the backups it can restore.

Deployment-wide and JWT-only, like the rest of the plugin admin API. Starting an upgrade is
approving the newer package (`admin_plugins`); a restore carries the phrase its dialog shows.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.databases.restore_service import PluginRestoreService
from plugins.lifecycle.upgrade_service import PluginUpgradeService
from plugins.serializers.admin import PluginDetailSerializer
from plugins.serializers.purge import VerificationPhraseSerializer
from plugins.serializers.upgrade import PluginBackupListSerializer, PluginRestoreSerializer
from plugins.views.admin_plugins import ADMIN_AUTHENTICATION, ADMIN_PERMISSIONS, plugin_details


class PluginUpgradeAdminView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS


class PluginUpgradeCancelView(PluginUpgradeAdminView):
    """Cancel the open upgrade: the plugin goes back to the version it ran."""

    @extend_schema(request=None, responses=PluginDetailSerializer)
    def post(self, request, identifier: str):
        PluginUpgradeService().cancel(identifier, request.user)
        return Response(plugin_details(identifier))


class PluginUpgradeRetryView(PluginUpgradeAdminView):
    """Run the failed stage of the open upgrade again."""

    @extend_schema(request=None, responses={202: PluginDetailSerializer})
    def post(self, request, identifier: str):
        PluginUpgradeService().retry(identifier, request.user)
        return Response(plugin_details(identifier), status=status.HTTP_202_ACCEPTED)


class PluginBackupListView(PluginUpgradeAdminView):
    @extend_schema(responses=PluginBackupListSerializer)
    def get(self, request, identifier: str):
        backups = PluginRestoreService().backups_of(identifier)
        return Response(PluginBackupListSerializer(backups).data)


class PluginBackupRestoreView(PluginUpgradeAdminView):
    """Replace the plugin's database with a backup of the open, failed upgrade."""

    @extend_schema(request=VerificationPhraseSerializer, responses={202: PluginRestoreSerializer})
    def post(self, request, identifier: str, backup_id: int):
        restore = PluginRestoreService().request(identifier, backup_id, request.data, request.user)
        return Response(PluginRestoreSerializer(restore).data, status=status.HTTP_202_ACCEPTED)
