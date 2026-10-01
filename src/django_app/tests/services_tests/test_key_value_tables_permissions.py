import pytest

from rbac.access.builtin_roles import BuiltInRoleSeeder
from rbac.access.catalog import grantable_bits_for
from rbac.access.effective import EffectivePermissions
from rbac.models import Organization, Role, RolePermission
from rbac.models.enums import BuiltInRole, Permission, ResourceType

CRUD = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE


def test_catalog_grants_crud_but_not_use_on_key_value_tables():
    assert grantable_bits_for(ResourceType.KEY_VALUE_TABLES.value) == CRUD


@pytest.mark.django_db
def test_seeded_builtin_roles_get_key_value_tables_grants_without_use():
    BuiltInRoleSeeder().seed()

    masks = {
        row.role.name: row.permissions
        for row in RolePermission.objects.filter(
            resource_type=ResourceType.KEY_VALUE_TABLES.value,
            role__is_built_in=True,
            role__org__isnull=True,
        ).select_related("role")
    }

    assert masks == {
        BuiltInRole.ORG_ADMIN: int(CRUD),
        BuiltInRole.MEMBER: int(Permission.READ),
        BuiltInRole.VIEWER: int(Permission.READ),
    }


@pytest.mark.django_db
def test_a_custom_role_use_bit_on_key_value_tables_survives_seeding_but_grants_nothing():
    org = Organization.objects.create(name="Custom key-value grants")
    role = Role.objects.create(name="Custom", org=org, is_built_in=False)
    grant = RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.KEY_VALUE_TABLES.value,
        permissions=int(Permission.READ | Permission.USE),
    )
    org_admin = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)

    BuiltInRoleSeeder().seed()

    grant.refresh_from_db()
    assert grant.permissions == int(Permission.READ | Permission.USE)
    custom = EffectivePermissions.from_role(role)
    assert custom.to_action_codes()[ResourceType.KEY_VALUE_TABLES.value] == ["read"]
    assert EffectivePermissions.from_role(org_admin).covers(EffectivePermissions.bits_of(role))
