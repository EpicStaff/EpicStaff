"""Assigning a role cannot hand out plugin actions beyond the assigner's own."""

import pytest
from plugins.access.role_assignment_check import PluginRoleAssignmentCheck
from plugins.models import PluginRolePermission
from rbac.access.effective import EffectivePermissions
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

MEMBERSHIPS_URL = "/api/admin/memberships/"
EDITABLE_PERMISSIONS = [
    {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
    {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]


def _store_actions(grant, role, *actions):
    bits = 0
    for action in actions:
        bits |= int(Permission[action.upper()])
    PluginRolePermission.objects.create(grant=grant, role=role, permissions=bits)


@pytest.fixture
def weather_grant(running_plugin, grant_to, acme):
    return grant_to(running_plugin(user_permissions=EDITABLE_PERMISSIONS), acme)


@pytest.fixture
def assigner(make_member, acme, role_org_admin, weather_grant):
    """A custom role with every Org Admin permission of EpicStaff, but only View on Weather."""
    role = Role.objects.create(name="Admins without Weather edit", org=acme, is_built_in=False)
    RolePermission.objects.bulk_create(
        RolePermission(role=role, resource_type=row.resource_type, permissions=row.permissions)
        for row in role_org_admin.permissions_set.all()
    )
    _store_actions(weather_grant, role, "read")
    return make_member(acme, role, "assigner@example.com")


@pytest.fixture
def forecasters(make_custom_role, acme):
    return make_custom_role(acme, "Forecasters")


@pytest.fixture
def newcomer(django_user_model):
    return django_user_model.objects.create_user(email="newcomer@example.com", password="StrongPass123!")


def _add(client, organization, role, user):
    return client.post(MEMBERSHIPS_URL, {"org_id": organization.id, "role_id": role.id, "user_id": user.id}, format="json")


def _change(client, membership, role):
    return client.patch(f"{MEMBERSHIPS_URL}{membership.id}/", {"role_id": role.id}, format="json")


def test_adding_a_member_with_a_role_above_the_assigner_s_plugin_actions_is_refused(client_as, assigner, acme, weather_grant, forecasters, newcomer):
    _store_actions(weather_grant, forecasters, "read", "update")

    response = _add(client_as(assigner), acme, forecasters, newcomer)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_escalation_denied"
    assert not OrganizationUser.objects.filter(user=newcomer).exists()


def test_adding_a_member_with_a_role_within_the_assigner_s_plugin_actions_works(client_as, assigner, acme, weather_grant, forecasters, newcomer):
    _store_actions(weather_grant, forecasters, "read")

    assert _add(client_as(assigner), acme, forecasters, newcomer).status_code == 201


def test_a_built_in_role_s_manifest_defaults_count_too(client_as, assigner, acme, role_member, role_viewer, newcomer, django_user_model):
    refused = _add(client_as(assigner), acme, role_member, newcomer)
    other = django_user_model.objects.create_user(email="viewer-to-be@example.com", password="StrongPass123!")
    allowed = _add(client_as(assigner), acme, role_viewer, other)

    assert refused.status_code == 403
    assert refused.json()["code"] == "permission_escalation_denied"
    assert allowed.status_code == 201


def test_changing_a_member_s_role_above_the_assigner_s_plugin_actions_is_refused(client_as, assigner, acme, role_viewer, weather_grant, forecasters, newcomer):
    membership = OrganizationUser.objects.create(user=newcomer, org=acme, role=role_viewer)
    _store_actions(weather_grant, forecasters, "read", "delete")

    response = _change(client_as(assigner), membership, forecasters)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_escalation_denied"
    membership.refresh_from_db()
    assert membership.role == role_viewer


def test_an_org_admin_holding_every_action_may_assign_it(client_as, admin_acme, acme, weather_grant, forecasters, newcomer):
    _store_actions(weather_grant, forecasters, "read", "update", "delete")

    assert _add(client_as(admin_acme), acme, forecasters, newcomer).status_code == 201


def test_a_superadmin_may_assign_any_role(client_as, superadmin, acme, weather_grant, forecasters, newcomer):
    _store_actions(weather_grant, forecasters, "read", "update", "delete")

    assert _add(client_as(superadmin), acme, forecasters, newcomer).status_code == 201


def test_actions_on_a_suspended_grant_count_too(client_as, assigner, acme, weather_grant, forecasters, newcomer):
    _store_actions(weather_grant, forecasters, "read", "update")
    weather_grant.state = "suspended"
    weather_grant.save(update_fields=["state"])

    assert _add(client_as(assigner), acme, forecasters, newcomer).status_code == 403


def test_the_plugin_ceiling_applies_while_plugins_are_off(client_as, assigner, acme, weather_grant, forecasters, newcomer, settings):
    _store_actions(weather_grant, forecasters, "read", "update", "delete")
    settings.PLUGINS_ENABLED = False

    response = _add(client_as(assigner), acme, forecasters, newcomer)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_escalation_denied"


def test_an_organization_without_grants_costs_the_check_one_query(admin_acme, beta, newcomer, role_member, django_assert_num_queries, settings):
    settings.PLUGINS_ENABLED = False
    admin_of_beta = OrganizationUser.objects.create(user=admin_acme, org=beta, role=Role.objects.get(name="Org Admin", is_built_in=True))
    effective = EffectivePermissions.from_role(admin_of_beta.role)

    with django_assert_num_queries(1):
        PluginRoleAssignmentCheck().assert_assignable(effective=effective, role=role_member, org_id=beta.id)
