from django.db import migrations

# EST-3341: Org Admin needs to set the org's audit_retention_days via the new
# self-service settings endpoint (OrganizationSelfServiceViewSet, gated on
# ResourceType.ORGANIZATIONS + UPDATE via HasOrgPermission). 0183 seeded
# Org Admin's "organizations" bitmask as 0 ("Org Admin does not manage
# orgs") because at the time there was no Org-Admin-facing org endpoint at
# all - the only org-editing surface was OrganizationAdminViewSet, which is
# IsSuperadmin-gated directly and does NOT consult this bitmask. Granting
# UPDATE here only unlocks the new self-service settings endpoint; it does
# not affect the superadmin-only rename/create/deactivate/reactivate surface.
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
