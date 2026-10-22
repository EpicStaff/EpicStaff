from rest_framework import serializers

from plugins.access.available_plugins import AvailablePlugin
from plugins.origins import PluginOrigins
from plugins.serializers.admin import icon_url


class AvailablePluginSerializer(serializers.Serializer):
    """A plugin a member may open, as the left bar and the framed page need it."""

    identifier = serializers.CharField(source="plugin.identifier")
    name = serializers.CharField(source="plugin.name")
    icon_url = serializers.SerializerMethodField()
    frame_origin = serializers.SerializerMethodField()
    permissions = serializers.ListField(child=serializers.CharField())
    availability = serializers.ChoiceField(choices=["ready", "maintenance"])

    def get_icon_url(self, available: AvailablePlugin) -> str:
        return icon_url(available.plugin)

    def get_frame_origin(self, available: AvailablePlugin) -> str:
        return PluginOrigins().frame_origin(available.plugin.identifier)
