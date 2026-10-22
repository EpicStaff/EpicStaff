from django.db import migrations
from django.db.models import F

_FLOWS = "flows"
_READ = 2  # Permission.READ
_USE = 64  # Permission.USE


def grant_use_to_custom_roles(apps, schema_editor):
    """Grant flows:USE to every custom role that holds flows:READ.

    Running a flow used to need only flows:READ, so this keeps every custom role
    able to do what it could before flows:USE gated running. Built-in roles are left
    to `seed_builtin_roles`, which reconciles them from builtin_roles.json.
    """
    RolePermission = apps.get_model("rbac", "RolePermission")
    (
        RolePermission.objects.filter(resource_type=_FLOWS, role__is_built_in=False)
        .annotate(read_bit=F("permissions").bitand(_READ))
        .filter(read_bit=_READ)
        .update(permissions=F("permissions").bitor(_USE))
    )


def revoke_use_from_custom_roles(apps, schema_editor):
    """Clear flows:USE from every custom role: before this migration it gated nothing.

    Lossy: it also strips USE from custom roles granted it after the forward migration.
    Re-applying the forward migration restores USE only where flows:READ is held.
    """
    RolePermission = apps.get_model("rbac", "RolePermission")
    RolePermission.objects.filter(resource_type=_FLOWS, role__is_built_in=False).update(
        permissions=F("permissions").bitand(~_USE)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0006_merge_20261009_0941"),
    ]

    operations = [
        migrations.RunPython(grant_use_to_custom_roles, revoke_use_from_custom_roles),
    ]
