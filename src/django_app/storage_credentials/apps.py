from django.apps import AppConfig


class StorageCredentialsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "storage_credentials"

    def ready(self):
        from health_check.plugins import plugin_dir

        from storage_credentials.health_checks import (
            StorageCredentialIssuerHealthCheck,
        )

        plugin_dir.register(StorageCredentialIssuerHealthCheck)
