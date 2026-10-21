from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plugins"

    def ready(self):
        from rbac.governance.delete_resource_names import register_resource_names
        from rbac.governance.role_assignment_checks import register_role_assignment_check

        from plugins import checks  # noqa: F401
        from plugins.access.role_assignment_check import PluginRoleAssignmentCheck

        # Grants cascade from their organization, so the organization delete report names
        # them; a custom role's plugin actions are a detail of its grant and its role, both
        # already reported. Plugins and packages are deployment-wide and never cascade from
        # one.
        register_resource_names(
            {"plugins.PluginGrant": "plugin_grants"}, frozenset({"plugins.PluginRolePermission"})
        )
        # Assigning a role must not hand out plugin actions beyond the assigner's own.
        register_role_assignment_check(PluginRoleAssignmentCheck())
