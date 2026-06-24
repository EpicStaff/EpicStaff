from unittest.mock import MagicMock

import pytest

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission
from tables.services.rbac.effective_permissions import EffectivePermissions
from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.rbac.rbac_exceptions import (
    OrgContextRequiredError,
    OrgMembershipRequiredError,
)
from tables.services.rbac.utils.permission_bitmask import (
    actions_to_bitmask,
    bitmask_to_actions,
)


def test_actions_to_bitmask_empty():
    assert actions_to_bitmask([]) == 0


def test_actions_to_bitmask_single():
    assert actions_to_bitmask(["read"]) == int(Permission.READ)


def test_actions_to_bitmask_combined():
    expected = int(Permission.CREATE | Permission.READ | Permission.UPDATE)
    assert actions_to_bitmask(["create", "read", "update"]) == expected


def test_actions_to_bitmask_unknown_raises():
    with pytest.raises(ValueError, match="Unknown action code"):
        actions_to_bitmask(["fly"])


def test_bitmask_to_actions_filters_by_applicable():
    bitmask = int(Permission.READ | Permission.CREATE | Permission.EXPORT)
    result = bitmask_to_actions(
        bitmask, applicable=["create", "read", "update", "delete"]
    )
    assert set(result) == {"create", "read"}


def test_bitmask_to_actions_preserves_catalog_order():
    bitmask = int(Permission.READ | Permission.CREATE | Permission.UPDATE)
    result = bitmask_to_actions(
        bitmask, applicable=["create", "read", "update", "delete", "export"]
    )
    assert result == ["create", "read", "update"]


def test_effective_permissions_superadmin_can_anything():
    eff = EffectivePermissions(is_superadmin=True, role=None, by_resource={})
    assert eff.can("flows", Permission.DELETE) is True
    assert eff.can("anything", Permission.EXPORT) is True


def test_effective_permissions_non_superadmin_respects_bitmask():
    eff = EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={"flows": int(Permission.READ | Permission.UPDATE)},
    )
    assert eff.can("flows", Permission.READ) is True
    assert eff.can("flows", Permission.UPDATE) is True
    assert eff.can("flows", Permission.DELETE) is False
    assert eff.can("agents", Permission.READ) is False  # not in by_resource


def test_to_action_codes_superadmin_returns_star():
    eff = EffectivePermissions(is_superadmin=True, role=None, by_resource={})
    assert eff.to_action_codes() == "*"


def test_to_action_codes_non_superadmin_returns_per_resource_lists():
    eff = EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={
            "flows": int(Permission.READ | Permission.CREATE),
            "agents": int(Permission.READ),
        },
    )
    result = eff.to_action_codes()
    assert isinstance(result, dict)
    assert set(result["flows"]) == {"create", "read"}
    assert result["agents"] == ["read"]


# ---- DB fixtures for resolver tests ----


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_acme(db):
    return Organization.objects.create(name="Acme Inc (resolver tests)")


@pytest.fixture
def superadmin_user(db, django_user_model):
    return django_user_model.objects.create_superuser(
        email="super-resolver@example.com", password="StrongPass123!"
    )


@pytest.fixture
def org_admin_user(db, django_user_model, org_acme, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-resolver@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_org_admin)
    return user


@pytest.fixture
def member_user(db, django_user_model, org_acme, role_member):
    user = django_user_model.objects.create_user(
        email="member-resolver@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_acme, role=role_member)
    return user


@pytest.fixture
def resolver():
    return PermissionResolver()


# ---- Resolver tests ----


@pytest.mark.django_db
def test_resolver_superadmin_bypass(resolver, superadmin_user, org_acme):
    effective = resolver.resolve(user=superadmin_user, org_id=org_acme.id)
    assert effective.is_superadmin is True
    assert effective.can("anything", Permission.DELETE) is True


@pytest.mark.django_db
def test_resolver_org_admin_membership(resolver, org_admin_user, org_acme):
    effective = resolver.resolve(user=org_admin_user, org_id=org_acme.id)
    assert effective.is_superadmin is False
    assert effective.role.name == "Org Admin"
    # Org Admin has CRUD on users per the seed (users bitmask = 15).
    assert effective.can("users", Permission.UPDATE) is True
    # Org Admin has no permissions on organizations resource per seed.
    assert effective.can("organizations", Permission.DELETE) is False


@pytest.mark.django_db
def test_resolver_no_membership_raises(resolver, member_user, db):
    other_org = Organization.objects.create(name="Other Inc (resolver tests)")
    with pytest.raises(OrgMembershipRequiredError):
        resolver.resolve(user=member_user, org_id=other_org.id)


@pytest.mark.django_db
def test_resolver_inactive_org_raises_for_non_superadmin(
    resolver, member_user, org_acme
):
    org_acme.is_active = False
    org_acme.save(update_fields=["is_active"])
    with pytest.raises(OrgMembershipRequiredError):
        resolver.resolve(user=member_user, org_id=org_acme.id)


@pytest.mark.django_db
def test_resolver_inactive_org_allowed_for_superadmin(
    resolver, superadmin_user, org_acme
):
    org_acme.is_active = False
    org_acme.save(update_fields=["is_active"])
    effective = resolver.resolve(user=superadmin_user, org_id=org_acme.id)
    assert effective.is_superadmin is True


# ---- OrgContextService ----


def _request_with_header(value, user=None):
    request = MagicMock()
    request.headers = {"X-Organization-Id": value} if value is not None else {}
    request.user = user
    return request


@pytest.fixture
def org_context():
    return OrgContextService()


@pytest.mark.django_db
def test_org_context_url_kwarg_wins(org_context, member_user, org_acme):
    request = _request_with_header("999", user=member_user)
    assert (
        org_context.resolve(request=request, view_kwargs={"org_id": org_acme.id})
        == org_acme.id
    )


@pytest.mark.django_db
def test_org_context_falls_back_to_header(org_context, member_user, org_acme):
    request = _request_with_header(str(org_acme.id), user=member_user)
    assert org_context.resolve(request=request, view_kwargs={}) == org_acme.id


@pytest.mark.django_db
def test_org_context_missing_raises(org_context, member_user):
    request = _request_with_header(None, user=member_user)
    with pytest.raises(OrgContextRequiredError):
        org_context.resolve(request=request, view_kwargs={})


@pytest.mark.django_db
def test_org_context_malformed_header_raises(org_context, member_user):
    request = _request_with_header("not-an-int", user=member_user)
    with pytest.raises(OrgContextRequiredError):
        org_context.resolve(request=request, view_kwargs={})


@pytest.mark.django_db
def test_org_context_member_of_other_org_raises(org_context, member_user):
    other = Organization.objects.create(name="Other Inc (org-context tests)")
    request = _request_with_header(str(other.id), user=member_user)
    with pytest.raises(OrgMembershipRequiredError):
        org_context.resolve(request=request, view_kwargs={})


@pytest.mark.django_db
def test_org_context_superadmin_bypass(org_context, superadmin_user):
    other = Organization.objects.create(name="Other Inc 2 (org-context tests)")
    request = _request_with_header(str(other.id), user=superadmin_user)
    assert org_context.resolve(request=request, view_kwargs={}) == other.id
