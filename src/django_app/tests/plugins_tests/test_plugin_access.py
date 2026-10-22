"""The one rule for who may use a plugin in an organization, and `available` built on it."""

import pytest
from plugins.access.available_plugins import plugins_available_to
from plugins.access.plugin_access import (
    eligible_organizations,
    gateway_person_facts,
    resolve_person_plugin_access,
)
from plugins.models import GrantState, PluginGrant, PluginRolePermission, PluginState
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole, Permission
from rbac.identity.api_keys.principals import SystemServicePrincipal

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PERMISSIONS = [
    {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]


@pytest.fixture
def weather(running_plugin):
    return running_plugin(user_permissions=PERMISSIONS)


@pytest.fixture
def grant(weather, grant_to, acme):
    return grant_to(weather, acme)


def _store(grant, role, *actions):
    bits = 0
    for action in actions:
        bits |= int(Permission[action.upper()])
    PluginRolePermission.objects.create(grant=grant, role=role, permissions=bits)


# Each case returns the person to judge in Acme; the expected actions are None when they may
# not use Weather there.
def _org_admin(context):
    return context["admin_acme"]


def _member(context):
    return context["member_only"]


def _viewer(context):
    return context["make_member"](context["acme"], context["role_viewer"], "viewer-access@example.com")


def _custom_role_with_view(context):
    role = context["make_custom_role"](context["acme"], "Forecasters")
    _store(context["grant"], role, "read", "delete")
    return context["make_member"](context["acme"], role, "custom-view@example.com")


def _custom_role_without_view(context):
    role = context["make_custom_role"](context["acme"], "Editors")
    _store(context["grant"], role, "update")
    return context["make_member"](context["acme"], role, "custom-no-view@example.com")


def _custom_role_with_nothing_stored(context):
    role = context["make_custom_role"](context["acme"], "Bystanders")
    return context["make_member"](context["acme"], role, "custom-nothing@example.com")


def _non_member(context):
    return context["make_member"](context["beta"], context["role_member"], "non-member@example.com")


def _inactive_user(context):
    user = context["member_only"]
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


def _inactive_organization(context):
    Organization.objects.filter(pk=context["acme"].pk).update(is_active=False)
    return context["member_only"]


def _suspended_grant(context):
    PluginGrant.objects.filter(pk=context["grant"].pk).update(state=GrantState.SUSPENDED)
    return context["member_only"]


def _plugin_not_running(context):
    context["weather"].__class__.objects.filter(pk=context["weather"].pk).update(state=PluginState.FAILED)
    return context["member_only"]


def _superadmin_non_member(context):
    return context["superadmin"]


def _superadmin_member(context):
    OrganizationUser.objects.create(user=context["superadmin"], org=context["acme"], role=context["role_member"])
    return context["superadmin"]


def _superadmin_membership_role(context):
    # The bootstrap SuperAdmin's membership holds the built-in Superadmin role.
    superadmin_role = Role.objects.get(name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=context["superadmin"], org=context["acme"], role=superadmin_role)
    return context["superadmin"]


def _demoted_superadmin_membership_role(context):
    # The Superadmin-role membership counts only while its holder is a SuperAdmin.
    user = _superadmin_membership_role(context)
    type(user).objects.filter(pk=user.pk).update(is_superadmin=False)
    user.refresh_from_db()
    return user


def _system_principal(context):
    return SystemServicePrincipal()


MATRIX = [
    (_org_admin, ["read", "update", "delete"]),
    (_member, ["read", "update"]),
    (_viewer, None),
    (_custom_role_with_view, ["read", "delete"]),
    (_custom_role_without_view, None),
    (_custom_role_with_nothing_stored, None),
    (_non_member, None),
    (_inactive_user, None),
    (_inactive_organization, None),
    (_suspended_grant, None),
    (_plugin_not_running, None),
    (_superadmin_non_member, None),
    (_superadmin_member, ["read", "update"]),
    (_superadmin_membership_role, ["read", "update", "delete"]),
    (_demoted_superadmin_membership_role, None),
    (_system_principal, None),
]


@pytest.fixture
def context(weather, grant, acme, beta, admin_acme, member_only, superadmin, role_member, role_viewer, make_member, make_custom_role):
    return locals()


@pytest.mark.parametrize(("person", "expected"), MATRIX, ids=[case.__name__.strip("_") for case, _ in MATRIX])
def test_the_eligibility_matrix(context, person, expected):
    user = person(context)

    access = resolve_person_plugin_access(user, context["acme"].pk, context["weather"])

    if expected is None:
        assert access is None
    else:
        assert (access.user, access.organization, access.grant, access.actions) == (
            user,
            context["acme"],
            context["grant"],
            expected,
        )


@pytest.mark.parametrize(("person", "expected"), MATRIX, ids=[case.__name__.strip("_") for case, _ in MATRIX])
def test_available_lists_exactly_what_the_rule_allows(context, person, expected):
    user = person(context)

    available = plugins_available_to(user, context["acme"].pk)

    assert [(plugin.plugin.identifier, plugin.permissions) for plugin in available] == (
        [] if expected is None else [("weather", expected)]
    )


@pytest.mark.parametrize(("person", "expected"), MATRIX, ids=[case.__name__.strip("_") for case, _ in MATRIX])
def test_eligible_organizations_follow_the_rule(context, person, expected):
    user = person(context)

    assert eligible_organizations(user, context["weather"]) == ([] if expected is None else [context["acme"]])


def test_eligible_organizations_are_the_person_s_own_sorted_by_name(member_only, role_member, weather, grant_to, acme, beta, make_member):
    zulu = Organization.objects.create(name="zulu-access")
    alpha = Organization.objects.create(name="Alpha-access")
    for organization in (acme, beta, zulu, alpha):
        grant_to(weather, organization)
    for organization in (zulu, alpha):
        OrganizationUser.objects.create(user=member_only, org=organization, role=role_member)
    make_member(beta, role_member, "someone-else@example.com")

    assert [organization.name for organization in eligible_organizations(member_only, weather)] == [
        "Acme-xorg",
        "Alpha-access",
        "zulu-access",
    ]


def test_resolving_one_organization_takes_a_fixed_number_of_queries(member_only, acme, weather, grant, django_assert_max_num_queries):
    with django_assert_max_num_queries(3):
        assert resolve_person_plugin_access(member_only, acme.pk, weather) is not None


def test_listing_eligible_organizations_of_built_in_roles_takes_two_queries(member_only, role_member, acme, beta, weather, grant_to, django_assert_num_queries):
    grant_to(weather, acme)
    grant_to(weather, beta)
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)

    with django_assert_num_queries(2):
        assert len(eligible_organizations(member_only, weather)) == 2


# ---- the gateway's facts, split into "token no longer acceptable" and "may not use" ----


def _facts(user_id, org_id, grant_id):
    return gateway_person_facts(user_id=user_id, org_id=org_id, grant_id=grant_id, identifier="weather")


def test_gateway_facts_of_an_eligible_person(member_only, acme, grant):
    facts = _facts(member_only.pk, acme.pk, grant.pk)

    assert (facts.user, facts.grant, facts.membership.org, facts.actions, facts.may_use) == (
        member_only,
        grant,
        acme,
        ["read", "update"],
        True,
    )


def test_gateway_facts_name_a_missing_user_or_grant(member_only, acme, grant, beta, grant_to, weather):
    other_grant = grant_to(weather, beta)

    assert _facts(999999, acme.pk, grant.pk).user is None
    assert _facts(member_only.pk, acme.pk, other_grant.pk).grant is None
    assert _facts(member_only.pk, acme.pk, 999999).grant is None


def test_gateway_facts_of_a_person_who_may_not_use_the_plugin(make_member, role_viewer, acme, grant):
    viewer = make_member(acme, role_viewer, "viewer-facts@example.com")

    facts = _facts(viewer.pk, acme.pk, grant.pk)

    assert (facts.grant, facts.may_use, facts.actions) == (grant, False, [])
