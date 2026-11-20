"""Put every sandbox venv and custom library in the scope of the organization that owns it.

The sandbox keeps custom library names unique per scope and resolves a venv's custom
libraries within its scope; rows created before scopes existed have none. Only this
database knows which organization owns which row, so the backfill is done from here.
"""

from django.db import migrations
from foundation.transport.http.errors import ClientNotFoundError
from loguru import logger
from proxies.sandbox.clients import SandboxCustomLibraryClient, SandboxVenvClient

BINDING_CLIENTS = (
    ("SandboxVenvBinding", SandboxVenvClient),
    ("SandboxCustomLibraryBinding", SandboxCustomLibraryClient),
)


def scope_sandbox_resources(apps, schema_editor):
    """Send each bound row its organization's scope.

    A binding whose row the sandbox no longer has is skipped with a warning: there is
    nothing left to scope, and failing the upgrade over it would help no one. Any other
    failure, an unreachable sandbox included, stops the migration so it runs again.
    """
    for model_name, client_class in BINDING_CLIENTS:
        bindings = list(
            apps.get_model("proxies", model_name)
            .objects.exclude(org_id=None)
            .values_list("resource_id", "org_id")
        )
        if not bindings:
            continue
        with client_class() as client:
            for resource_id, org_id in bindings:
                try:
                    # Frozen copy of `sandbox_scope`: the org id as a string.
                    client.update(resource_id, {"scope": str(org_id)})
                except ClientNotFoundError:
                    logger.warning(
                        "Sandbox has no row {} for a {}; left unscoped", resource_id, model_name
                    )


class Migration(migrations.Migration):
    dependencies = [
        ("proxies", "0003_sandboxcustomlibrarybinding"),
    ]

    operations = [
        migrations.RunPython(scope_sandbox_resources, migrations.RunPython.noop),
    ]
