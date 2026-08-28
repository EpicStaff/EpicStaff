from django.db import migrations


_SURFACE_BITMASKS = {
    "Org Admin": 15,  # C R U D
    "Member": 7,      # C R U
    "Viewer": 2,      # R
    # Superadmin: intentionally no row — authority via User.is_superadmin.
}
_RESOURCE = "surfaces"


def seed(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")
    for role_name, bitmask in _SURFACE_BITMASKS.items():
        try:
            role = Role.objects.get(
                name=role_name, is_built_in=True, org__isnull=True
            )
        except Role.DoesNotExist:
            continue
        RolePermission.objects.update_or_create(
            role=role,
            resource_type=_RESOURCE,
            defaults={"permissions": bitmask},
        )


def unseed(apps, schema_editor):
    RolePermission = apps.get_model("tables", "RolePermission")
    RolePermission.objects.filter(
        role__is_built_in=True, resource_type=_RESOURCE
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0204_alter_rolepermission_resource_type"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
