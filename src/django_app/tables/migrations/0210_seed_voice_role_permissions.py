# Seeds RolePermission rows for ResourceType.VOICE, following the exact
# pattern of 0183_seed_builtin_role_permissions.py.
#
# `voice` was added to ResourceType/permission_catalog but no migration ever
# seeded RolePermission rows for it — EffectivePermissions.can() defaults a
# missing resource_type to bitmask 0, so every non-superadmin org user got
# 403 on any VOICE-gated endpoint (RealtimeChannelViewSet, TwilioChannelViewSet)
# regardless of role.
#
# Voice is a config-group resource like llm_configs (see permission_catalog's
# RESOURCE_TYPE_METADATA "group": "config") — bitmask shape mirrors the
# llm_configs row in 0183's _BITMASKS exactly: Org Admin=15 (CRUD),
# Member=2 (R), Viewer=2 (R).
#
# Scoped reverse (only deletes resource_type="voice" rows) so re-running the
# down migration doesn't clobber other resource types' seeded permissions.

from django.db import migrations


_BITMASKS = {
    "Org Admin": 15,  # C R U D
    "Member": 2,       # R
    "Viewer": 2,       # R
}


def seed_voice_permissions(apps, schema_editor):
    Role = apps.get_model("tables", "Role")
    RolePermission = apps.get_model("tables", "RolePermission")

    for role_name, bitmask in _BITMASKS.items():
        try:
            role = Role.objects.get(
                name=role_name, is_built_in=True, org__isnull=True
            )
        except Role.DoesNotExist:
            continue
        RolePermission.objects.update_or_create(
            role=role,
            resource_type="voice",
            defaults={"permissions": bitmask},
        )
    # Superadmin role: intentionally no RolePermission rows. Authority
    # flows from User.is_superadmin.


def remove_voice_permissions(apps, schema_editor):
    RolePermission = apps.get_model("tables", "RolePermission")
    RolePermission.objects.filter(
        role__is_built_in=True, resource_type="voice"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0209_realtime_channel_org_not_null"),
    ]

    operations = [
        migrations.RunPython(seed_voice_permissions, remove_voice_permissions),
    ]
