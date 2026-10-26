from rest_framework import serializers

from plugins.identity.login_protocol import AUTHORIZE_PATH, TOKEN_PATH
from plugins.models import Plugin
from plugins.origins import PluginOrigins


class PublicConfigSerializer(serializers.Serializer):
    """The platform config a plugin's SPA loads from /.well-known/epicstaff/config.json."""

    FRAME_PROTOCOL = 1
    API_BASE = "/api/"

    plugin = serializers.SerializerMethodField()
    epicstaff_origin = serializers.SerializerMethodField()
    frame_protocol = serializers.SerializerMethodField()
    api_base = serializers.SerializerMethodField()
    login = serializers.SerializerMethodField()

    def get_plugin(self, plugin: Plugin) -> dict:
        return {
            "identifier": plugin.identifier,
            "name": plugin.name,
            "version": plugin.current_package.version,
        }

    def get_epicstaff_origin(self, plugin: Plugin) -> str:
        return PluginOrigins().epicstaff_origin

    def get_frame_protocol(self, plugin: Plugin) -> int:
        return self.FRAME_PROTOCOL

    def get_api_base(self, plugin: Plugin) -> str:
        return self.API_BASE

    def get_login(self, plugin: Plugin) -> dict | None:
        """Where the SDK logs a person in; None for a plugin without a backend, which has no
        `/api/` a login token could be used at."""
        if plugin.current_package.parsed_manifest.backend is None:
            return None
        epicstaff_origin = PluginOrigins().epicstaff_origin
        return {
            "authorize_url": f"{epicstaff_origin}{AUTHORIZE_PATH}",
            "token_url": f"{epicstaff_origin}{TOKEN_PATH}",
        }
