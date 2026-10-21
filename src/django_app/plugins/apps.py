from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plugins"

    def ready(self):
        from rbac.governance.delete_resource_names import register_resource_names
        from rbac.governance.role_assignment_checks import register_role_assignment_check

        from plugins import checks  # noqa: F401
        from plugins.access.role_assignment_check import PluginRoleAssignmentCheck
        from plugins.ownership.ownership_recorder import connect_ownership_recorder

        # Grants cascade from their organization, so the organization delete report names
        # them; a custom role's plugin actions, a grant's service account and its keys, and
        # what the plugin owns there are details of the grant or of the resources, both
        # already reported. Plugins, packages, hook jobs and activity events are
        # deployment-wide and never cascade from one.
        register_resource_names(
            {"plugins.PluginGrant": "plugin_grants"},
            frozenset(
                {
                    "plugins.PluginRolePermission",
                    "plugins.PluginServiceAccount",
                    "plugins.PluginServiceAccountKey",
                    "plugins.PluginOwnedResource",
                }
            ),
        )
        # Assigning a role must not hand out plugin actions beyond the assigner's own.
        register_role_assignment_check(PluginRoleAssignmentCheck())
        connect_ownership_recorder()
