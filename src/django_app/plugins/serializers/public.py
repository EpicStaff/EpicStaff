from rest_framework import serializers

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

    def get_login(self, plugin: Plugin) -> None:
        return None
