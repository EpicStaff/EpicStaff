from django.db import migrations


BUILTIN_ROLES = [
    # name, description, permissions dict {resource_type: bitmask}
    (
        "Superadmin",
        "Display-only role. Access is granted via User.is_superadmin bypass, "
        "so no RolePermission rows are needed.",
        {},
    ),
    (
        "Org Admin",
        "Full control within an organization.",
        {
            "flows": 31,           # C R U D E
            "agents": 15,          # C R U D
            "tools": 15,
            "knowledge_sources": 15,
            "files": 47,           # C R U D dl
            "projects": 15,
            "llm_configs": 15,
            "secrets": 207,        # C R U D use list
            "users": 15,
            "roles": 15,
        },
    ),
    (
        "Member",
        "CRU on most resources, no delete, no user/role management.",
        {
            "flows": 7,            # C R U
            "agents": 7,
            "tools": 7,
            "knowledge_sources": 2,  # R
            "files": 39,             # C R U dl
            "projects": 7,
            "llm_configs": 2,
            "secrets": 192,          # use list
            "users": 0,
            "roles": 0,
        },
    ),
    (
        "Viewer",
        "Read-only across resources; can run flows and use secrets.",
        {
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
        },
    ),
]


def seed_builtin_roles(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    for name, description, perms in BUILTIN_ROLES:
        role, _created = Role.objects.get_or_create(
            name=name,
            is_built_in=True,
            org=None,
            defaults={"description": description},
        )
        for resource_type, bitmask in perms.items():
            RolePermission.objects.update_or_create(
                role=role,
                resource_type=resource_type,
                defaults={"permissions": bitmask},
            )


def unseed_builtin_roles(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    Role.objects.filter(
        is_built_in=True,
        org__isnull=True,
        name__in=[name for name, _, _ in BUILTIN_ROLES],
    ).delete()  # cascades RolePermission


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0170_rbac_and_persistent_models"),
    ]

    operations = [
        migrations.RunPython(seed_builtin_roles, unseed_builtin_roles),
    ]
