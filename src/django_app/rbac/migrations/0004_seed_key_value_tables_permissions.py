from django.db import migrations

_INTENDED = {
    ("Org Admin", "key_value_tables"): 15,  # C R U D
    ("Member", "key_value_tables"): 2,  # R
    ("Viewer", "key_value_tables"): 2,  # R
}


def _write(apps, masks_by_role_resource):
    Role = apps.get_model("rbac", "Role")
    RolePermission = apps.get_model("rbac", "RolePermission")

    roles = {}
    for (role_name, resource_type), bitmask in masks_by_role_resource.items():
        if role_name not in roles:
            roles[role_name] = Role.objects.filter(
                name=role_name, is_built_in=True, org__isnull=True
            ).first()
        role = roles[role_name]
        if role is None:
            continue
        RolePermission.objects.update_or_create(
            role=role, resource_type=resource_type, defaults={"permissions": bitmask}
        )


def seed_key_value_tables_permissions(apps, schema_editor):
    _write(apps, _INTENDED)


def remove_key_value_tables_permissions(apps, schema_editor):
    RolePermission = apps.get_model("rbac", "RolePermission")
    role_names = {role_name for role_name, _ in _INTENDED}
    RolePermission.objects.filter(
        resource_type="key_value_tables",
        role__name__in=role_names,
        role__is_built_in=True,
        role__org__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0003_key_value_tables_resource_type"),
    ]

    operations = [
        migrations.RunPython(seed_key_value_tables_permissions, remove_key_value_tables_permissions),
    ]
