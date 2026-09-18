import pytest

from tables.models.rbac_models import Role, RolePermission
from tables.models.rbac_models.rbac_enums import BuiltInRole, ResourceType


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role_name,expected",
    [
        (BuiltInRole.ORG_ADMIN, 15),
        (BuiltInRole.MEMBER, 7),
        (BuiltInRole.VIEWER, 2),
    ],
)
def test_builtin_roles_have_surface_grants(role_name, expected):
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    rp = RolePermission.objects.get(
        role=role, resource_type=ResourceType.SURFACES.value
    )
    assert rp.permissions == expected


@pytest.mark.django_db
def test_superadmin_has_no_surface_grant():
    role = Role.objects.get(
        name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True
    )
    assert not RolePermission.objects.filter(
        role=role, resource_type=ResourceType.SURFACES.value
    ).exists()
