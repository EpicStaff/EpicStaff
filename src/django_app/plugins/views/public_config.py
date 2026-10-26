"""Public plugin endpoints: what a running plugin's SPA needs, and the icons EpicStaff shows
for it: the plugin's icon in the Apps list and the icons of its app menu.

No login: the SPA must load before anyone can log in, and an icon is drawn from a plain URL
that sends no token. They answer only for running plugins, and plugins stopped for an
upgrade (whose entry in the Apps list and app menu stay), serve only the current package's
icons, and reveal nothing beyond what the public SPA shows.
"""

from django.db.models import F
from django.http import HttpResponse
from epicstaff_plugin.package_layout import NAVIGATION_ICONS_DIRECTORY
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.exceptions import PluginNotFoundError, SigningKeyMissingError
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.models import Plugin, PluginPackageNavigationIcon, PluginState
from plugins.serializers.public import PublicConfigSerializer

CONFIG_CACHE_CONTROL = "public, max-age=60"
ICON_CACHE_CONTROL = "public, max-age=3600"
JWKS_CACHE_CONTROL = "public, max-age=300"
# An SVG opened directly must not run anything or load anything.
ICON_CONTENT_SECURITY_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
SERVED_PLUGIN_STATES = (PluginState.RUNNING, PluginState.MAINTENANCE)


def _running_plugin(identifier: str, *deferred_fields: str) -> Plugin:
    plugin = (
        Plugin.objects.select_related("current_package")
        .defer(*(f"current_package__{field}" for field in deferred_fields))
        .filter(
            identifier=identifier,
            state__in=SERVED_PLUGIN_STATES,
            current_package__isnull=False,
        )
        .first()
    )
    if plugin is None:
        raise PluginNotFoundError()
    return plugin


def _icon_response(data: bytes, media_type: str) -> HttpResponse:
    response = HttpResponse(data, content_type=media_type)
    response["Cache-Control"] = ICON_CACHE_CONTROL
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = ICON_CONTENT_SECURITY_POLICY
    return response


class PublicPluginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class PluginPublicConfigView(PublicPluginView):
    def get(self, request, identifier: str):
        plugin = _running_plugin(identifier, "icon_bytes")
        response = Response(PublicConfigSerializer(plugin).data)
        response["Cache-Control"] = CONFIG_CACHE_CONTROL
        return response


class PluginIconView(PublicPluginView):
    def get(self, request, identifier: str):
        package = _running_plugin(identifier, "manifest").current_package
        return _icon_response(bytes(package.icon_bytes), package.icon_media_type)


class PluginNavigationIconView(PublicPluginView):
    """An icon of the app menu, `icons/<file_name>` of the plugin's current package.

    A file only another package of the plugin holds (a pending one, or an earlier version)
    is not found, like an unknown one.
    """

    def get(self, request, identifier: str, file_name: str):
        icon = (
            PluginPackageNavigationIcon.objects.filter(
                path=NAVIGATION_ICONS_DIRECTORY + file_name,
                package__plugin__identifier=identifier,
                package__plugin__state__in=SERVED_PLUGIN_STATES,
                package__plugin__current_package=F("package"),
            )
            .only("media_type", "icon_bytes")
            .first()
        )
        if icon is None:
            raise PluginNotFoundError()
        return _icon_response(bytes(icon.icon_bytes), icon.media_type)


class PluginJwksView(PublicPluginView):
    """The keys gateway contexts are signed with, for a plugin that meets an unknown key id."""

    def get(self, request):
        try:
            jwks = PluginSigningKeyService().jwks().model_dump(mode="json")
        except SigningKeyMissingError:
            # Before the first start with plugins on; nothing to verify with, nothing cached.
            response = Response({"keys": []})
            response["Cache-Control"] = "no-store"
            return response
        response = Response(jwks)
        response["Cache-Control"] = JWKS_CACHE_CONTROL
        return response
