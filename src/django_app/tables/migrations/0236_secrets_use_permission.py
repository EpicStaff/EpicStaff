from django.db import migrations


_FORWARD = {"Member": 128, "Viewer": 128}
_REVERSE = {"Member": 192, "Viewer": 192}


def _set_builtin_secrets_masks(apps, schema_editor, *, masks):
    """Update the `secrets` RolePermission row for each named built-in role to the given mask."""
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    for role_name, bitmask in masks.items():
        try:
            role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
        except Role.DoesNotExist:
            continue
        RolePermission.objects.update_or_create(
            role=role,
            resource_type="secrets",
            defaults={"permissions": bitmask},
        )


def grant_use_to_custom_roles(apps, schema_editor):
    """Preserve today's effective behaviour for custom roles by granting secrets:USE wherever flows:UPDATE is already held."""
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    editor_role_ids = [
        row.role_id
        for row in RolePermission.objects.filter(resource_type="flows")
        if row.permissions & 4
    ]
    for role in Role.objects.filter(is_built_in=False, id__in=editor_role_ids):
        row, _ = RolePermission.objects.get_or_create(
            role=role, resource_type="secrets", defaults={"permissions": 0}
        )
        row.permissions |= 64  # Permission.USE
        row.save(update_fields=["permissions"])


def revoke_builtin_use(apps, schema_editor):
    """Revoke secrets:USE from Member and Viewer, leaving Org Admin at 207 and custom roles untouched."""
    _set_builtin_secrets_masks(apps, schema_editor, masks=_FORWARD)


def restore_builtin_use(apps, schema_editor):
    """Restore Member and Viewer secrets masks to 192, undoing the revocation on reverse migrate."""
    _set_builtin_secrets_masks(apps, schema_editor, masks=_REVERSE)


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0235_merge_20260904_1022"),
    ]

    operations = [
        migrations.RunPython(revoke_builtin_use, restore_builtin_use),
        migrations.RunPython(grant_use_to_custom_roles, migrations.RunPython.noop),
    ]
