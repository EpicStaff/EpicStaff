from django.db import migrations
from django.db.models import F

# Permission.USE. A literal, like the masks in 0004: a migration must not follow the enum.
_USE = 64


def strip_persistent_data_use(apps, schema_editor):
    """Clear USE from every persistent_data grant, built-in and custom roles alike.

    persistent_data no longer has a USE action: a node's mode decides which permissions it
    needs. Re-running clears nothing more.
    """
    RolePermission = apps.get_model("rbac", "RolePermission")
    RolePermission.objects.filter(resource_type="persistent_data").update(
        permissions=F("permissions").bitand(~_USE)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0004_seed_persistent_data_permissions"),
    ]

    operations = [
        migrations.RunPython(strip_persistent_data_use, migrations.RunPython.noop),
    ]
