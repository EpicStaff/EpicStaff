"""SuperAdmin management of a plugin's backend: settings, limits, runtime and restart.

Deployment-wide, JWT only, like the rest of /api/admin/plugins/. Only for a plugin whose
current package has a backend; any other plugin answers 409 `plugin_has_no_backend`.
"""

from epicstaff_plugin.contracts.manifest import PluginManifest
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.configuration.limits import PluginLimitsService, plugin_limits
from plugins.configuration.setting_values import PluginSettingsService
from plugins.exceptions import PluginHasNoBackendError, PluginNotFoundError
from plugins.models import Plugin
from plugins.nodes.plugin_runtime_service import PluginRuntimeService
from plugins.serializers.backend import (
    PluginLimitsResponseSerializer,
    PluginLimitsUpdateSerializer,
    PluginRuntimeResponseSerializer,
    PluginSettingsResponseSerializer,
    PluginSettingsUpdateSerializer,
)
from plugins.views.admin_plugins import ADMIN_PERMISSIONS


def _backend_plugin(identifier: str) -> tuple[Plugin, PluginManifest]:
    plugin = (
        Plugin.objects.select_related("current_package")
        .defer("current_package__icon_bytes")
        .filter(identifier=identifier)
        .first()
    )
    if plugin is None:
        raise PluginNotFoundError()
    if plugin.current_package is None:
        raise PluginHasNoBackendError()
    manifest = plugin.current_package.parsed_manifest
    if manifest.backend is None:
        raise PluginHasNoBackendError()
    return plugin, manifest


class PluginBackendAdminView(APIView):
    # Pinned rather than inherited from the defaults, so no credential a later version adds
    # for plugins can ever authenticate here.
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = ADMIN_PERMISSIONS


class PluginSettingsView(PluginBackendAdminView):
    _service = PluginSettingsService()

    def get(self, request, identifier: str):
        plugin, manifest = _backend_plugin(identifier)
        return Response(
            PluginSettingsResponseSerializer(self._service.settings_of(plugin, manifest)).data
        )

    def patch(self, request, identifier: str):
        plugin, manifest = _backend_plugin(identifier)
        body = PluginSettingsUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        updated = self._service.update(
            plugin, manifest, body.validated_data["values"], request.user
        )
        return Response(PluginSettingsResponseSerializer(updated).data)


class PluginLimitsView(PluginBackendAdminView):
    def get(self, request, identifier: str):
        plugin, manifest = _backend_plugin(identifier)
        return Response(PluginLimitsResponseSerializer(plugin_limits(plugin, manifest)).data)

    def patch(self, request, identifier: str):
        plugin, manifest = _backend_plugin(identifier)
        body = PluginLimitsUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        limits = PluginLimitsService().update_overrides(
            plugin, manifest, body.validated_data["overrides"], request.user
        )
        return Response(PluginLimitsResponseSerializer(limits).data)


class PluginRuntimeView(PluginBackendAdminView):
    def get(self, request, identifier: str):
        plugin, manifest = _backend_plugin(identifier)
        return Response(
            PluginRuntimeResponseSerializer(
                PluginRuntimeService().runtime_of(plugin, manifest)
            ).data
        )


class PluginRestartView(PluginBackendAdminView):
    def post(self, request, identifier: str):
        plugin, manifest = _backend_plugin(identifier)
        runtime = PluginRuntimeService().restart(plugin, manifest, request.user)
        return Response(
            PluginRuntimeResponseSerializer(runtime).data, status=status.HTTP_202_ACCEPTED
        )
