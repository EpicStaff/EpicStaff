from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from plugins.access.available_plugins import AVAILABILITIES, UNAVAILABLE, AvailablePlugin
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
    availability = serializers.ChoiceField(
        choices=AVAILABILITIES,
        help_text=(
            "ready: open it in its frame. maintenance: it is being updated. unavailable: its host "
            "is served by another server, not this EpicStaff; it must not be framed."
        ),
    )
    development = serializers.BooleanField(
        help_text="Served from a developer's machine by plugin development mode."
    )
    navigation = serializers.SerializerMethodField()

    def get_icon_url(self, available: AvailablePlugin) -> str:
        return icon_url(available.plugin)

    @extend_schema_field(
        serializers.CharField(
            allow_null=True,
            help_text=(
                "The only origin the plugin's page is framed from; null while the plugin is "
                "unavailable, so not even an outdated page of EpicStaff can frame its host."
            ),
        )
    )
    def get_frame_origin(self, available: AvailablePlugin) -> str | None:
        if available.availability == UNAVAILABLE:
            return None
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
