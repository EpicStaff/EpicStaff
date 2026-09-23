import pytest

from tables.models.rbac_models import OrganizationUser
from tables.serializers.membership_serializers import MembershipResponseSerializer

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_membership_row_shape(admin_acme, acme, role_org_admin):
    m = OrganizationUser.objects.select_related("user", "org", "role").get(
        user=admin_acme, org=acme
    )
    data = MembershipResponseSerializer(m).data
    assert data["id"] == m.id
    assert data["org"] == {"id": acme.id, "name": acme.name}
    assert data["user"]["email"] == admin_acme.email
    assert set(data["user"].keys()) == {
        "id",
        "email",
        "display_name",
        "avatar_url",
        "is_active",
    }
    assert data["user"]["avatar_url"] is None
    assert data["role"] == {"id": role_org_admin.id, "name": role_org_admin.name}
    assert "joined_at" in data
