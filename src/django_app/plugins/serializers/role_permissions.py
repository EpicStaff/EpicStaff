from rest_framework import serializers

from plugins.access.role_permission_service import PluginRoleRow, RequestedPluginActions
from plugins.packages.review import action_label
from plugins.serializers.admin import icon_url

# A plugin declares at most every action once; anything longer is not a real request.
MAX_ACTIONS_PER_PLUGIN = 16
MAX_PLUGINS_PER_ROLE = 1000


class OrganizationRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class RequiredOrganizationQuerySerializer(serializers.Serializer):
    org_id = serializers.IntegerField(min_value=1)


class OptionalOrganizationQuerySerializer(serializers.Serializer):
    org_id = serializers.IntegerField(min_value=1, required=False)


class PluginRoleRowSerializer(serializers.Serializer):
    """A plugin row of the Roles matrix: the plugin, its declared actions and the ceiling."""

    plugin_identifier = serializers.CharField(source="plugin.identifier")
    name = serializers.CharField(source="plugin.name")
    icon_url = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    ceiling = serializers.ListField(child=serializers.CharField())

    def get_icon_url(self, row: PluginRoleRow) -> str:
        return icon_url(row.plugin)

    def get_actions(self, row: PluginRoleRow) -> list[dict]:
        return [
            {
                "action": permission.action,
                "label": action_label(permission.action),
                "description": permission.description,
            }
            for permission in row.plugin.current_package.parsed_manifest.user_permissions
        ]


class PluginRoleGrantedRowSerializer(PluginRoleRowSerializer):
    granted = serializers.ListField(child=serializers.CharField())


class PluginRoleRowsResponseSerializer(serializers.Serializer):
    organization = OrganizationRefSerializer()
    rows = PluginRoleRowSerializer(many=True)


class RoleRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_built_in = serializers.BooleanField()
    org_id = serializers.IntegerField(allow_null=True)


class PluginRolePermissionsResponseSerializer(serializers.Serializer):
    role = RoleRefSerializer()
    organization = OrganizationRefSerializer(allow_null=True)
    editable = serializers.BooleanField()
    rows = PluginRoleGrantedRowSerializer(many=True)


class RequestedPluginActionsSerializer(serializers.Serializer):
    """One plugin of a write. Only the form is checked here; the service checks the rest."""

    plugin_identifier = serializers.CharField(max_length=64)
    actions = serializers.ListField(
        child=serializers.CharField(max_length=32), max_length=MAX_ACTIONS_PER_PLUGIN
    )

    def to_internal_value(self, data) -> RequestedPluginActions:
        values = super().to_internal_value(data)
        return RequestedPluginActions(
            plugin_identifier=values["plugin_identifier"], actions=values["actions"]
        )


class PluginRolePermissionsUpdateSerializer(serializers.Serializer):
    plugins = serializers.ListField(
        child=RequestedPluginActionsSerializer(), max_length=MAX_PLUGINS_PER_ROLE
    )
