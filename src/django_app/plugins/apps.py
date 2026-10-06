from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plugins"

    def ready(self):
        from rbac.governance.delete_resource_names import register_resource_names

        # Plugins cascade from their organization, so the delete report must name
        # them; their registry and asset rows are implied by "plugins".
        register_resource_names(
            {"plugins.Plugin": "plugins"},
            frozenset({"plugins.PluginResource", "plugins.PluginAsset"}),
        )
