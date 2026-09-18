from django.db import migrations

_OLD_BITMASK = 0
_NEW_BITMASK = 4  # UPDATE only


def grant_update(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    try:
        role = Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)
    except Role.DoesNotExist:
        return
    RolePermission.objects.update_or_create(
        role=role,
        resource_type="organizations",
        defaults={"permissions": _NEW_BITMASK},
    )


def revert_update(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    try:
        role = Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)
    except Role.DoesNotExist:
        return
    RolePermission.objects.update_or_create(
        role=role,
        resource_type="organizations",
        defaults={"permissions": _OLD_BITMASK},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0210_create_organization_config"),
    ]

    operations = [
        migrations.RunPython(grant_update, revert_update),
    ]
