from django.db import migrations

# EST-3324: AUDIT resource seeded onto built-in roles via migration, same
# mechanism every other resource uses (see 0183_seed_builtin_role_permissions).
# EST-3325 (live grant/revoke API) is formally descoped for this epic - no
# grant/revoke mechanism exists anywhere in this codebase yet, and this
# epic doesn't build the first one. Org Admin gets READ+EXPORT (2+16=18)
# by default; Member/Viewer get 0 - unredacted org-wide audit data is
# opt-in-by-admin-only, not something every role should see out of the box.
_BITMASKS = {
    "Org Admin": 18,
    "Member": 0,
    "Viewer": 0,
}


def seed_audit_permissions(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    for role_name, bitmask in _BITMASKS.items():
        try:
            role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
        except Role.DoesNotExist:
            continue
        RolePermission.objects.update_or_create(
            role=role,
            resource_type="audit",
            defaults={"permissions": bitmask},
        )
    # Superadmin: intentionally no RolePermission rows, same as every other
    # resource - authority flows from User.is_superadmin, bypassing bitmask checks.


def remove_audit_permissions(apps, schema_editor):
    # Scoped to resource_type="audit" only - must not touch any other
    # resource's RolePermission rows seeded by earlier migrations.
    RolePermission = apps.get_model("tables", "RolePermission")
    RolePermission.objects.filter(
        role__is_built_in=True, resource_type="audit"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0208_sessiontrigger_and_backfill"),
    ]

    operations = [
        migrations.RunPython(seed_audit_permissions, remove_audit_permissions),
    ]
