from django.db import migrations


_BITMASKS = {
    "Org Admin": {
        "flows": 31,             # C R U D E
        "agents": 31,            # C R U D E
        "tools": 15,
        "knowledge_sources": 15,
        "files": 31,             # C R U D E
        "projects": 31,          # C R U D E
        "llm_configs": 15,
        "secrets": 207,          # C R U D use list
        "users": 15,
        "roles": 15,
        "organizations": 0,      # Org Admin does not manage orgs
    },
    "Member": {
        "flows": 7,              # C R U
        "agents": 7,
        "tools": 7,
        "knowledge_sources": 2,  # R
        "files": 23,             # C R U E
        "projects": 7,
        "llm_configs": 2,
        "secrets": 192,          # use list
        "users": 0,
        "roles": 0,
        "organizations": 0,
    },
    "Viewer": {
        "flows": 66,             # R use
        "agents": 2,
        "tools": 2,
        "knowledge_sources": 2,
        "files": 2,
        "projects": 2,
        "llm_configs": 2,
        "secrets": 192,          # use list
        "users": 0,
        "roles": 0,
        "organizations": 0,
    },
}


def seed_role_permissions(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    for role_name, by_resource in _BITMASKS.items():
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
    # Superadmin role: intentionally no RolePermission rows. Authority
    # flows from User.is_superadmin.


def remove_role_permissions(apps, schema_editor):
    RolePermission = apps.get_model("tables", "RolePermission")
    RolePermission.objects.filter(role__is_built_in=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0182_resource_type_add_organizations"),
    ]

    operations = [
        migrations.RunPython(seed_role_permissions, remove_role_permissions),
    ]
