import pytest

from tables.models.rbac_models import Organization, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.serializers.permission_serializers import RoleResponseSerializer


@pytest.mark.django_db
def test_custom_role_serializes_org_object():
    org = Organization.objects.create(name="Acme-ser")
    role = Role.objects.create(name="Custom", org=org, is_built_in=False)
    role._perm_rows = []
    role._assigned_count = 0
    role._effective_org_id = org.id
    data = RoleResponseSerializer(role).data
    assert data["org"] == {"id": org.id, "name": "Acme-ser"}


@pytest.mark.django_db
def test_builtin_role_serializes_null_org():
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    role._perm_rows = []
    role._assigned_count = 0
    role._effective_org_id = None
    data = RoleResponseSerializer(role).data
    assert data["org"] is None
