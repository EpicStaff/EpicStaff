from django.db import migrations


# Bitmasks are built from tables.services.rbac.permissions.Permission flags:
#   CREATE=1, READ=2, UPDATE=4, DELETE=8, EXPORT=16
#
# EST-3207: tools gained an export/import feature. Built-in roles were seeded
# (0183_seed_builtin_role_permissions) before EXPORT existed for `tools`, so
# their `tools` bitmask is missing bit 16. This mirrors the shape already
# used for `flows`/`agents`/`projects` (Org Admin: C R U D E; Member: C R U E,
# no D — same shape `files` already uses for Member).
_FORWARD_BITMASKS = {
    "Org Admin": {"tools": 31},  # 15 (C R U D) + 16 (E) = 31, matches flows/agents
    "Member": {"tools": 23},     # 7 (C R U) + 16 (E) = 23, matches files' Member shape
}

_REVERSE_BITMASKS = {
    "Org Admin": {"tools": 15},  # original 0183 value
    "Member": {"tools": 7},      # original 0183 value
}


def _apply_bitmasks(apps, bitmasks_by_role):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    for role_name, by_resource in bitmasks_by_role.items():
        try:
            role = Role.objects.get(
                name=role_name, is_built_in=True, org__isnull=True
            )
        except Role.DoesNotExist:
            continue
        for resource_type, bitmask in by_resource.items():
            RolePermission.objects.update_or_create(
                role=role,
                resource_type=resource_type,
                defaults={"permissions": bitmask},
            )


def grant_tools_export(apps, schema_editor):
    _apply_bitmasks(apps, _FORWARD_BITMASKS)


def revert_tools_export(apps, schema_editor):
    _apply_bitmasks(apps, _REVERSE_BITMASKS)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0209_remove_pythoncodetool_favorite_mcptoolfavorite_and_more"),
    ]

    operations = [
        migrations.RunPython(grant_tools_export, revert_tools_export),
    ]
