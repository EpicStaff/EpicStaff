import pytest

from tables.models.rbac_models import Role, RolePermission
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission


@pytest.mark.django_db
def test_org_admin_has_org_read_update():
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    rp = RolePermission.objects.get(role=role, resource_type="organizations")
    assert rp.permissions == int(Permission.READ | Permission.UPDATE)  # 6


@pytest.mark.django_db
def test_member_and_viewer_have_no_org_permission():
    for name in (BuiltInRole.MEMBER, BuiltInRole.VIEWER):
        role = Role.objects.get(name=name, is_built_in=True, org__isnull=True)
        rp = RolePermission.objects.filter(
            role=role, resource_type="organizations"
        ).first()
        assert rp is None or rp.permissions == 0
