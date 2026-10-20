from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plugins"

    def ready(self):
        from rbac.governance.delete_resource_names import register_resource_names

        from plugins import checks  # noqa: F401

        # Grants cascade from their organization, so the organization delete report names
        # them. Plugins and packages are deployment-wide and never cascade from one.
        register_resource_names({"plugins.PluginGrant": "plugin_grants"}, frozenset())
