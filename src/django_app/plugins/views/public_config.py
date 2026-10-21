"""Public plugin endpoints: what a running plugin's SPA and its left-bar icon need.

No login: the SPA must load before anyone can log in, and an `<img>` sends no token. They
answer only for running plugins and reveal nothing beyond what the public SPA shows.
"""

from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.exceptions import PluginNotFoundError, SigningKeyMissingError
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.models import Plugin, PluginState
from plugins.serializers.public import PublicConfigSerializer

CONFIG_CACHE_CONTROL = "public, max-age=60"
ICON_CACHE_CONTROL = "public, max-age=3600"
JWKS_CACHE_CONTROL = "public, max-age=300"
# An SVG opened directly must not run anything or load anything.
ICON_CONTENT_SECURITY_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def _running_plugin(identifier: str, *deferred_fields: str) -> Plugin:
    plugin = (
        Plugin.objects.select_related("current_package")
        .defer(*(f"current_package__{field}" for field in deferred_fields))
        .filter(identifier=identifier, state=PluginState.RUNNING, current_package__isnull=False)
        .first()
    )
    if plugin is None:
        raise PluginNotFoundError()
    return plugin


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
        response = HttpResponse(bytes(package.icon_bytes), content_type=package.icon_media_type)
        response["Cache-Control"] = ICON_CACHE_CONTROL
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = ICON_CONTENT_SECURITY_POLICY
        return response


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
