"""How many members hold a role, as the roles API shows it (`assigned_count`,
`assigned_by_org`, `org`).

Two rules, because the two role kinds differ. A custom role belongs to exactly
one org, so its holders can only be there and the count is unambiguous. A
built-in role is one row shared by every org, so it is counted across the
organizations the request is scoped to -- and the Superadmin row is never
counted at all.
"""

import pytest

from rbac.governance.roles import RoleManagementService
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rbac.serializers.permissions import RoleResponseSerializer

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _holder(django_user_model, org, role, email):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)


def _shown(role, scope_org_ids) -> dict:
    """The role as the roles endpoints render it for a request scoped to `scope_org_ids`."""
    role = Role.objects.select_related("org").prefetch_related("permissions_set").get(pk=role.pk)
    RoleManagementService().attach_role_display(roles=[role], scope_org_ids=scope_org_ids)
    return RoleResponseSerializer(role).data


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("scope", "expected_count", "expected_orgs"),
    [
        ("acme", 2, ["acme"]),
        # Superadmin requests are unscoped: every org, sorted by name.
        (None, 3, ["acme", "beta"]),
        ("nothing", 0, []),
        # An org in scope with no holders gets no breakdown entry.
        ("acme+empty", 2, ["acme"]),
    ],
)
def test_built_in_role_is_counted_across_the_request_scope(
    django_user_model, acme, beta, role_member, scope, expected_count, expected_orgs
):
    empty = Organization.objects.create(name="empty-count")
    _holder(django_user_model, acme, role_member, "m-acme-1@example.com")
    _holder(django_user_model, acme, role_member, "m-acme-2@example.com")
    _holder(django_user_model, beta, role_member, "m-beta-1@example.com")
    orgs = {"acme": acme, "beta": beta}
    scope_org_ids = {
        "acme": {acme.id}, None: None, "nothing": set(), "acme+empty": {acme.id, empty.id}
    }[scope]

    shown = _shown(role_member, scope_org_ids)

    assert shown["org"] is None
    assert shown["assigned_count"] == expected_count
    assert [entry["org"]["id"] for entry in shown["assigned_by_org"]] == [orgs[name].id for name in expected_orgs]
    assert sum(entry["count"] for entry in shown["assigned_by_org"]) == expected_count


@pytest.mark.django_db
def test_breakdown_is_sorted_by_org_name_case_insensitively(django_user_model, role_member):
    zeta = Organization.objects.create(name="zeta-count")
    alpha = Organization.objects.create(name="Alpha-count")
    _holder(django_user_model, zeta, role_member, "m-zeta@example.com")
    _holder(django_user_model, alpha, role_member, "m-alpha@example.com")

    shown = _shown(role_member, None)

    assert [entry["org"]["name"] for entry in shown["assigned_by_org"]] == ["Alpha-count", "zeta-count"]


@pytest.mark.django_db
def test_superadmin_role_is_never_counted(django_user_model, acme):
    # A bootstrap-style membership carrying the Superadmin role: migration 0211
    # retains exactly this shape, so it is present in real deployments.
    superadmin = Role.objects.get(name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True)
    _holder(django_user_model, acme, superadmin, "sa-holder@example.com")

    shown = _shown(superadmin, None)

    assert (shown["assigned_count"], shown["assigned_by_org"]) == (0, [])


@pytest.mark.django_db
@pytest.mark.parametrize("holders", [2, 0])
def test_custom_role_is_counted_in_its_own_org_whatever_the_scope(django_user_model, acme, holders):
    billing = Role.objects.create(name="Billing-count", org=acme, is_built_in=False)
    for index in range(holders):
        _holder(django_user_model, acme, billing, f"c-acme-{index}@example.com")

    # An empty scope must not zero a custom role: its holders can only be in its
    # own org, and the caller was already authorized against it there.
    shown = _shown(billing, set())

    assert shown["org"] == {"id": acme.id, "name": acme.name}
    assert shown["assigned_count"] == holders
    assert shown["assigned_by_org"] == (
        [{"org": {"id": acme.id, "name": acme.name}, "count": holders}] if holders else []
    )
