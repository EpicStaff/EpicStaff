import pytest

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType
from tables.services.rbac.effective_permissions import EffectivePermissions
from tables.services.rbac.cross_org_permission_resolver import (
    CrossOrgPermissionResolver,
)


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


def test_from_role_builds_by_resource(role_member):
    eff = EffectivePermissions.from_role(role_member)
    assert eff.is_superadmin is False
    assert eff.role == role_member
    # Member seed grants projects=CRU; roles=0.
    assert eff.can(ResourceType.PROJECTS.value, Permission.READ) is True
    assert eff.can(ResourceType.ROLES.value, Permission.READ) is False


@pytest.mark.django_db
def test_resolve_all_returns_scope_per_active_membership(
    django_user_model, role_org_admin, role_member
):
    user = django_user_model.objects.create_user(
        email="multi@example.com", password="StrongPass123!"
    )
    acme = Organization.objects.create(name="Acme")
    beta = Organization.objects.create(name="Beta")
    inactive = Organization.objects.create(name="Zeta", is_active=False)
    OrganizationUser.objects.create(user=user, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    OrganizationUser.objects.create(user=user, org=inactive, role=role_org_admin)

    scopes = CrossOrgPermissionResolver().resolve_all(user=user)

    assert [s.org.name for s in scopes] == ["Acme", "Beta"]  # active only, name-ordered
    acme_scope = scopes[0]
    assert acme_scope.effective.can(ResourceType.ROLES.value, Permission.CREATE) is True
    beta_scope = scopes[1]
    assert (
        beta_scope.effective.can(ResourceType.ROLES.value, Permission.CREATE) is False
    )
