from importlib import import_module

import pytest
from django.apps import apps

from rbac.models import Organization, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rbac.access.catalog import grantable_bits_for


def test_catalog_grants_crud_but_not_use_on_key_value_tables():
    assert grantable_bits_for(ResourceType.KEY_VALUE_TABLES.value) == (
        Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
    )


@pytest.mark.django_db
def test_builtin_roles_get_key_value_tables_grants():
    masks = {
        row.role.name: row.permissions
        for row in RolePermission.objects.filter(
            resource_type=ResourceType.KEY_VALUE_TABLES.value,
            role__is_built_in=True,
            role__org__isnull=True,
        ).select_related("role")
    }
    assert masks == {"Org Admin": 15, "Member": 2, "Viewer": 2}


@pytest.mark.django_db
def test_0005_strips_use_only_from_key_value_tables():
    org = Organization.objects.create(name="Strip use")
    role = Role.objects.create(name="Custom", org=org, is_built_in=False)
    key_value_tables = RolePermission.objects.create(
        role=role, resource_type=ResourceType.KEY_VALUE_TABLES.value, permissions=79
    )
    secrets = RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.SECRETS.value,
        permissions=int(Permission.USE | Permission.READ),
    )
    strip = import_module("rbac.migrations.0005_strip_key_value_tables_use").strip_key_value_tables_use

    strip(apps, None)
    strip(apps, None)

    key_value_tables.refresh_from_db()
    secrets.refresh_from_db()
    assert key_value_tables.permissions == 15
    assert secrets.permissions == int(Permission.USE | Permission.READ)
