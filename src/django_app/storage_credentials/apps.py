from django.apps import AppConfig


class StorageCredentialsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "storage_credentials"

    def ready(self):
        # Registers the custom /ht/ backend only -- no Redis I/O happens
        # here. The actual issuer/reconciler process is a separate
        # management command (run_storage_credential_issuer), started once
        # from entrypoint.sh, not from this hook (which runs in every
        # worker process).
        from health_check.plugins import plugin_dir

        from storage_credentials.health_checks import (
            StorageCredentialIssuerHealthCheck,
        )

        plugin_dir.register(StorageCredentialIssuerHealthCheck)
