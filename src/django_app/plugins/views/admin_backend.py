"""SuperAdmin management of a plugin's backend: settings, limits, runtime and restart.

Deployment-wide, JWT only, like the rest of /api/admin/plugins/. Only for a plugin whose node
package (`node_package`: an upgrade's target once the plugin is stopped for it, else the
current package) has a backend; any other plugin answers 409 `plugin_has_no_backend`. The
settings and limits are read and checked against that package. While the plugin is
uninstalled its settings and limits stay editable, for a reinstall; once it is being deleted,
they answer 409 `plugin_uninstalling`, and so does a restart while it is uninstalled.
"""

from epicstaff_plugin.contracts.manifest import PluginManifest
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.configuration.limits import PluginLimitsService, plugin_limits
from plugins.configuration.setting_values import PluginSettingsService
from plugins.exceptions import PluginHasNoBackendError, PluginNotFoundError
from plugins.lifecycle.open_upgrades import node_package, open_upgrade_of
from plugins.models import Plugin, PluginPackage
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
    plugin, package = _backend_plugin_and_package(identifier)
    return plugin, package.parsed_manifest


def _backend_plugin_and_package(identifier: str) -> tuple[Plugin, PluginPackage]:
    """The plugin and its node package, which must have a backend."""
    plugin = (
        Plugin.objects.select_related("current_package")
        .defer("current_package__icon_bytes")
        .filter(identifier=identifier)
        .first()
    )
    if plugin is None:
        raise PluginNotFoundError()
    package = node_package(plugin, open_upgrade_of(plugin))
    if package is None or package.parsed_manifest.backend is None:
        raise PluginHasNoBackendError()
    return plugin, package


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
        plugin, package = _backend_plugin_and_package(identifier)
        return Response(
            PluginRuntimeResponseSerializer(PluginRuntimeService().runtime_of(plugin, package)).data
        )


class PluginRestartView(PluginBackendAdminView):
    def post(self, request, identifier: str):
        plugin, package = _backend_plugin_and_package(identifier)
        runtime = PluginRuntimeService().restart(plugin, package, request.user)
        return Response(
            PluginRuntimeResponseSerializer(runtime).data, status=status.HTTP_202_ACCEPTED
        )
