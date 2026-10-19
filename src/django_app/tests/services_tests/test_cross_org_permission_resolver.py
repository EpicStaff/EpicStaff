import pytest

from rbac.models import Organization, OrganizationUser, Role, RoleAuditPolicy
from rbac.access.resolver import PermissionResolver
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from rbac.access.effective import EffectivePermissions
from rbac.access.cross_org_resolver import (
    CrossOrgPermissionResolver,
)

# tests/conftest.py has an autouse `heal_builtin_roles` fixture that queries the
# Role table before every db test. Without this marker, pytest-django never
# swaps the connection to the test database for tests that only pull db access
# in transitively through another fixture, so that query hits a blocked connection.
pytestmark = pytest.mark.django_db


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


@pytest.mark.django_db
def test_resolve_all_loads_audit_limits_without_a_query_per_org(
    django_user_model, django_assert_num_queries, role_member
):
    user = django_user_model.objects.create_user(
        email="limits@example.com", password="StrongPass123!"
    )
    for index in range(3):
        org = Organization.objects.create(name=f"Limited {index}")
        role = Role.objects.create(name=f"Limited auditor {index}", org=org, is_built_in=False)
        RoleAuditPolicy.objects.create(role=role, history_days=index + 1)
        OrganizationUser.objects.create(user=user, org=org, role=role)
    OrganizationUser.objects.create(
        user=user, org=Organization.objects.create(name="Unlimited"), role=role_member
    )

    # One query for the memberships (with role, org and policy joined), one prefetch.
    with django_assert_num_queries(2):
        scopes = CrossOrgPermissionResolver().resolve_all(user=user)
        limits = {scope.org.name: scope.effective.audit_history_days for scope in scopes}

    assert limits == {"Limited 0": 1, "Limited 1": 2, "Limited 2": 3, "Unlimited": 0}


@pytest.mark.django_db
def test_resolver_carries_the_audit_limit_and_superadmin_is_unlimited(django_user_model):
    user = django_user_model.objects.create_user(
        email="one-limit@example.com", password="StrongPass123!"
    )
    org = Organization.objects.create(name="One limit")
    role = Role.objects.create(name="One limit auditor", org=org, is_built_in=False)
    RoleAuditPolicy.objects.create(role=role, history_days=30)
    OrganizationUser.objects.create(user=user, org=org, role=role)
    superadmin = django_user_model.objects.create_user(
        email="limit-su@example.com", password="StrongPass123!", is_superadmin=True
    )

    assert PermissionResolver().resolve(user=user, org_id=org.id).audit_history_days == 30
    assert PermissionResolver().resolve(user=superadmin, org_id=org.id).audit_history_days == 0
