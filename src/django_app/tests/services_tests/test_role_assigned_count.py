"""The `assigned_count` / `assigned_by_org` rule, at service level.

Two rules, because the two role kinds differ. A custom role belongs to exactly
one org, so its holders can only be there and the count is unambiguous. A
built-in role is one row shared by every org, so it is counted across the
organizations the request is scoped to -- and the Superadmin row is never
counted at all.
"""

import pytest

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.role_management_service import RoleManagementService

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def role_superadmin(db):
    return Role.objects.get(
        name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True
    )


def _holder(django_user_model, org, role, email):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _reload(role):
    """Refetch with the prefetch `attach_role_display` expects."""
    return (
        Role.objects.select_related("org")
        .prefetch_related("permissions_set")
        .get(pk=role.pk)
    )


# ---- built-in roles: counted across the request's scope ----


@pytest.mark.django_db
def test_built_in_count_is_scoped_to_the_given_orgs(
    django_user_model, acme, beta, role_member
):
    _holder(django_user_model, acme, role_member, "m-acme-1@example.com")
    _holder(django_user_model, acme, role_member, "m-acme-2@example.com")
    _holder(django_user_model, beta, role_member, "m-beta-1@example.com")
    member = _reload(role_member)

    RoleManagementService().attach_role_display(roles=[member], scope_org_ids={acme.id})

    assert member._assigned_count == 2
    assert member._assigned_by_org == [
        {"org": {"id": acme.id, "name": "Acme-xorg"}, "count": 2}
    ]


@pytest.mark.django_db
def test_built_in_count_with_none_scope_counts_every_org(
    django_user_model, acme, beta, role_member
):
    _holder(django_user_model, acme, role_member, "m-acme-3@example.com")
    _holder(django_user_model, beta, role_member, "m-beta-2@example.com")
    member = _reload(role_member)

    RoleManagementService().attach_role_display(roles=[member], scope_org_ids=None)

    assert member._assigned_count == 2
    assert [entry["org"]["id"] for entry in member._assigned_by_org] == [
        acme.id,
        beta.id,
    ]


@pytest.mark.django_db
def test_built_in_count_with_empty_scope_counts_nothing(
    django_user_model, acme, role_member
):
    _holder(django_user_model, acme, role_member, "m-acme-4@example.com")
    member = _reload(role_member)

    RoleManagementService().attach_role_display(roles=[member], scope_org_ids=set())

    assert member._assigned_count == 0
    assert member._assigned_by_org == []


@pytest.mark.django_db
def test_built_in_breakdown_omits_orgs_with_no_holders(
    django_user_model, acme, beta, role_member
):
    _holder(django_user_model, acme, role_member, "m-acme-5@example.com")
    member = _reload(role_member)

    RoleManagementService().attach_role_display(
        roles=[member], scope_org_ids={acme.id, beta.id}
    )

    assert [entry["org"]["id"] for entry in member._assigned_by_org] == [acme.id]


@pytest.mark.django_db
def test_built_in_breakdown_is_sorted_by_org_name_case_insensitively(
    django_user_model, role_member
):
    zeta = Organization.objects.create(name="zeta-count")
    alpha = Organization.objects.create(name="Alpha-count")
    _holder(django_user_model, zeta, role_member, "m-zeta@example.com")
    _holder(django_user_model, alpha, role_member, "m-alpha@example.com")
    member = _reload(role_member)

    RoleManagementService().attach_role_display(roles=[member], scope_org_ids=None)

    assert [entry["org"]["name"] for entry in member._assigned_by_org] == [
        "Alpha-count",
        "zeta-count",
    ]


@pytest.mark.django_db
def test_assigned_count_equals_the_breakdown_sum(
    django_user_model, acme, beta, role_member
):
    _holder(django_user_model, acme, role_member, "m-sum-1@example.com")
    _holder(django_user_model, acme, role_member, "m-sum-2@example.com")
    _holder(django_user_model, beta, role_member, "m-sum-3@example.com")
    member = _reload(role_member)

    RoleManagementService().attach_role_display(roles=[member], scope_org_ids=None)

    assert member._assigned_count == sum(
        entry["count"] for entry in member._assigned_by_org
    )


# ---- the Superadmin row is never counted ----


@pytest.mark.django_db
def test_superadmin_role_is_never_counted(django_user_model, acme, role_superadmin):
    # A bootstrap-style membership carrying the Superadmin role: migration 0211
    # retains exactly this shape, so it is present in real deployments.
    _holder(django_user_model, acme, role_superadmin, "sa-holder@example.com")
    superadmin_role = _reload(role_superadmin)

    RoleManagementService().attach_role_display(
        roles=[superadmin_role], scope_org_ids=None
    )

    assert superadmin_role._assigned_count == 0
    assert superadmin_role._assigned_by_org == []


# ---- custom roles: counted in their own org, one breakdown entry ----


@pytest.mark.django_db
def test_custom_role_is_counted_in_its_own_org(django_user_model, acme):
    billing = Role.objects.create(name="Billing-count", org=acme, is_built_in=False)
    _holder(django_user_model, acme, billing, "c-acme-1@example.com")
    _holder(django_user_model, acme, billing, "c-acme-2@example.com")
    role = _reload(billing)

    # A custom role ignores the scope entirely: passing an empty selection must
    # not zero it, because its holders can only be in its own org and the
    # caller was already authorized against it there.
    RoleManagementService().attach_role_display(roles=[role], scope_org_ids=set())

    assert role._assigned_count == 2
    assert role._assigned_by_org == [
        {"org": {"id": acme.id, "name": "Acme-xorg"}, "count": 2}
    ]


@pytest.mark.django_db
def test_custom_role_with_no_holders_has_an_empty_breakdown(acme):
    role = _reload(Role.objects.create(name="Empty-count", org=acme, is_built_in=False))

    RoleManagementService().attach_role_display(roles=[role], scope_org_ids=None)

    assert role._assigned_count == 0
    assert role._assigned_by_org == []
