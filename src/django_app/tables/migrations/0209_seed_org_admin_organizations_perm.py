from django.db import migrations

from tables.models.rbac_models.rbac_enums import BuiltInRole

# Permission.READ | Permission.UPDATE — Org Admin may view the org-admin
# surface and rename/manage settings for its own org. create/deactivate stay
# platform-level (superadmin-only), so no CREATE/DELETE bit is granted.
ORG_READ_UPDATE = 6


def seed_org_admin_organizations_perm(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")
    role = Role.objects.filter(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    ).first()
    if role is None:
        return
    RolePermission.objects.update_or_create(
        role=role,
        resource_type="organizations",
        defaults={"permissions": ORG_READ_UPDATE},
    )


def unseed_org_admin_organizations_perm(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")
    role = Role.objects.filter(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    ).first()
    if role is None:
        return
    RolePermission.objects.filter(role=role, resource_type="organizations").update(
        permissions=0
    )


class Migration(migrations.Migration):
    dependencies = [("tables", "0208_sessiontrigger_and_backfill")]
    operations = [
        migrations.RunPython(
            seed_org_admin_organizations_perm,
            unseed_org_admin_organizations_perm,
        )
    ]
