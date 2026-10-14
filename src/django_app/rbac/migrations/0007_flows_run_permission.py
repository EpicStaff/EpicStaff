from django.db import migrations
from django.db.models import F

_FLOWS = "flows"
_READ = 2  # Permission.READ
_RUN = 256  # Permission.RUN


def grant_run_to_custom_roles(apps, schema_editor):
    """Grant flows:RUN to every custom role that holds flows:READ.

    Running a flow used to need only flows:READ, so this keeps every custom role
    able to do what it could before RUN existed. Built-in roles are left to
    `seed_builtin_roles`, which reconciles them from builtin_roles.json.
    """
    RolePermission = apps.get_model("rbac", "RolePermission")
    (
        RolePermission.objects.filter(resource_type=_FLOWS, role__is_built_in=False)
        .annotate(read_bit=F("permissions").bitand(_READ))
        .filter(read_bit=_READ)
        .update(permissions=F("permissions").bitor(_RUN))
    )


def revoke_run_from_custom_roles(apps, schema_editor):
    """Clear flows:RUN from every custom role: the bit does not exist before this migration.

    Lossy: it also strips RUN from custom roles granted it after the forward migration,
    and from roles the forward step never touched. Re-applying the forward migration
    restores RUN only where flows:READ is held.
    """
    RolePermission = apps.get_model("rbac", "RolePermission")
    RolePermission.objects.filter(resource_type=_FLOWS, role__is_built_in=False).update(
        permissions=F("permissions").bitand(~_RUN)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0006_merge_20261009_0941"),
    ]

    operations = [
        migrations.RunPython(grant_run_to_custom_roles, revoke_run_from_custom_roles),
    ]
