from rest_framework import serializers

from plugins.access.available_plugins import AvailablePlugin
from plugins.origins import PluginOrigins
from plugins.serializers.admin import icon_url, navigation_icon_url


class AvailablePluginSerializer(serializers.Serializer):
    """A plugin a member may open, as the Apps list, the app menu and the framed page need it.

    Name, description and menu follow the running version: the menu comes from the current
    package's manifest, which `plugins_available_to` already loaded, and is filtered by the
    `permissions` it already resolved, so it costs no query.
    """

    identifier = serializers.CharField(source="plugin.identifier")
    name = serializers.CharField(source="plugin.name")
    description = serializers.CharField(source="plugin.description")
    icon_url = serializers.SerializerMethodField()
    frame_origin = serializers.SerializerMethodField()
    permissions = serializers.ListField(child=serializers.CharField())
    availability = serializers.ChoiceField(choices=["ready", "maintenance"])
    development = serializers.BooleanField(
        help_text="Served from a developer's machine by plugin development mode."
    )
    navigation = serializers.SerializerMethodField()

    def get_icon_url(self, available: AvailablePlugin) -> str:
        return icon_url(available.plugin)

    def get_frame_origin(self, available: AvailablePlugin) -> str:
        return PluginOrigins().frame_origin(available.plugin.identifier)

    def get_navigation(self, available: AvailablePlugin) -> list[dict]:
        """The app menu entries the person sees, in the manifest's order; empty when the plugin
        declares none."""
        return [
            {
                "label": item.label,
                "path": item.path,
                "icon_url": navigation_icon_url(available.plugin, item.icon),
            }
            for item in available.visible_navigation
        ]
