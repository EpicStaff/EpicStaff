import pytest

from rbac.models import OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rbac.exceptions import (
    InactiveUserError,
    InvalidRoleAssignmentError,
    RoleNotFoundError,
    SuperadminNotAssignableError,
)
from rbac.governance.guards import UserManagementGuards

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_active_ordinary_user_is_assignable(django_user_model):
    target = django_user_model.objects.create_user(
        email="ok@x.com", password="StrongPass123!"
    )
    UserManagementGuards.assert_user_is_assignable_member(target)


@pytest.mark.django_db
def test_superadmin_is_not_assignable(django_user_model):
    target = django_user_model.objects.create_user(
        email="sa@x.com", password="StrongPass123!", is_superadmin=True
    )
    with pytest.raises(SuperadminNotAssignableError):
        UserManagementGuards.assert_user_is_assignable_member(target)


@pytest.mark.django_db
def test_inactive_user_is_not_assignable(django_user_model):
    target = django_user_model.objects.create_user(
        email="off@x.com", password="StrongPass123!", is_active=False
    )
    with pytest.raises(InactiveUserError):
        UserManagementGuards.assert_user_is_assignable_member(target)


@pytest.mark.django_db
def test_superadmin_precedes_inactive(django_user_model):
    """An inactive superadmin reports the superadmin reason — it is the
    structural one, and reactivating would not make them assignable."""
    target = django_user_model.objects.create_user(
        email="offsa@x.com",
        password="StrongPass123!",
        is_superadmin=True,
        is_active=False,
    )
    with pytest.raises(SuperadminNotAssignableError):
        UserManagementGuards.assert_user_is_assignable_member(target)


@pytest.mark.django_db
def test_membership_of_ordinary_user_is_assignable(
    django_user_model, acme, role_member
):
    user = django_user_model.objects.create_user(
        email="m@x.com", password="StrongPass123!"
    )
    membership = OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    UserManagementGuards.assert_membership_holder_is_assignable(membership)


@pytest.mark.django_db
def test_membership_of_superadmin_is_not_assignable(
    django_user_model, acme, role_member
):
    user = django_user_model.objects.create_user(
        email="msa@x.com", password="StrongPass123!", is_superadmin=True
    )
    membership = OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    with pytest.raises(SuperadminNotAssignableError):
        UserManagementGuards.assert_membership_holder_is_assignable(membership)


@pytest.mark.django_db
def test_builtin_and_own_custom_roles_are_assignable(acme, role_member):
    own = Role.objects.create(name="AcmeOnly", org=acme, is_built_in=False)
    for role in (role_member, own):
        assert UserManagementGuards.role_is_assignable(role, acme.id)
        UserManagementGuards.assert_role_is_assignable(role, acme.id)


@pytest.mark.django_db
def test_foreign_org_role_is_reported_as_not_found(acme, beta):
    foreign = Role.objects.create(name="BetaOnly", org=beta, is_built_in=False)
    assert not UserManagementGuards.role_is_assignable(foreign, acme.id)
    with pytest.raises(RoleNotFoundError):
        UserManagementGuards.assert_role_is_assignable(foreign, acme.id)


@pytest.mark.django_db
def test_superadmin_role_is_an_invalid_assignment(acme):
    superadmin_role = Role.objects.get(name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True)
    assert not UserManagementGuards.role_is_assignable(superadmin_role, acme.id)
    with pytest.raises(InvalidRoleAssignmentError):
        UserManagementGuards.assert_role_is_assignable(superadmin_role, acme.id)
