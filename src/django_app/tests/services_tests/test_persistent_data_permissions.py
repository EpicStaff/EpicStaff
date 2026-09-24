import pytest

from rbac.models import RolePermission
from rbac.models.enums import Permission, ResourceType
from rbac.access.catalog import grantable_bits_for


def test_catalog_grants_crud_and_use_on_persistent_data():
    assert grantable_bits_for(ResourceType.PERSISTENT_DATA.value) == (
        Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE | Permission.USE
    )


@pytest.mark.django_db
def test_builtin_roles_get_persistent_data_grants():
    masks = {
        row.role.name: row.permissions
        for row in RolePermission.objects.filter(
            resource_type=ResourceType.PERSISTENT_DATA.value,
            role__is_built_in=True,
            role__org__isnull=True,
        ).select_related("role")
    }
    assert masks == {"Org Admin": 79, "Member": 66, "Viewer": 2}
