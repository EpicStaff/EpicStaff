"""Which plugins a person may open in an organization (contract section 3, `available`)."""

import pytest
from plugins.models import GrantState, Plugin, PluginState
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.test import APIClient

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

AVAILABLE_URL = "/api/plugins/available/"

EDITABLE_PERMISSIONS = [
    {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
    {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]


@pytest.fixture
def make_member(django_user_model):
    def _make(organization, role, email):
        user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
        OrganizationUser.objects.create(user=user, org=organization, role=role)
        return user

    return _make


@pytest.fixture
def weather_in_acme(running_plugin, grant_to, acme):
    plugin = running_plugin()
    grant_to(plugin, acme)
    return plugin


def _available(client_as, user, organization):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(organization.id))
    return client.get(AVAILABLE_URL)


def test_a_member_whose_role_has_view_by_default_sees_the_plugin(client_as, member_only, acme, weather_in_acme):
    response = _available(client_as, member_only, acme)

    assert response.status_code == 200
    assert response.json() == [
        {
            "identifier": "weather",
            "name": "Weather",
            "icon_url": "/api/plugin-public/weather/icon/?v=0.1.0",
            "frame_origin": "http://weather.plugins.epicstaff.localhost",
            "permissions": ["read"],
        }
    ]


def test_an_org_admin_sees_the_plugin(client_as, admin_acme, acme, weather_in_acme):
    assert [plugin["identifier"] for plugin in _available(client_as, admin_acme, acme).json()] == ["weather"]


def test_a_viewer_without_the_default_view_sees_nothing(client_as, make_member, role_viewer, acme, weather_in_acme):
    viewer = make_member(acme, role_viewer, "viewer-plugins@example.com")

    response = _available(client_as, viewer, acme)

    assert response.status_code == 200
    assert response.json() == []


def test_a_custom_role_gets_nothing_even_with_every_epicstaff_permission(client_as, make_member, acme, weather_in_acme):
    role = Role.objects.create(name="Power user", org=acme, is_built_in=False)
    for resource_type in ResourceType:
        RolePermission.objects.create(role=role, resource_type=resource_type, permissions=int(Permission(127)))
    power_user = make_member(acme, role, "power-plugins@example.com")

    assert _available(client_as, power_user, acme).json() == []


def test_built_in_roles_get_the_manifest_defaults(client_as, make_member, admin_acme, member_only, role_viewer, acme, running_plugin, grant_to):
    grant_to(running_plugin(user_permissions=EDITABLE_PERMISSIONS), acme)
    viewer = make_member(acme, role_viewer, "viewer-defaults@example.com")

    permissions = {
        role: _available(client_as, user, acme).json()[0]["permissions"]
        for role, user in (("org_admin", admin_acme), ("member", member_only), ("viewer", viewer))
    }

    assert permissions == {"org_admin": ["read", "update", "delete"], "member": ["read", "update"], "viewer": ["read"]}


def test_a_member_of_another_organization_gets_nothing_of_it(client_as, make_member, role_member, beta, weather_in_acme):
    beta_member = make_member(beta, role_member, "member-beta-plugins@example.com")

    response = _available(client_as, beta_member, beta)

    assert response.status_code == 200
    assert response.json() == []


def test_naming_an_organization_one_is_not_a_member_of_is_refused(client_as, make_member, role_member, acme, beta, weather_in_acme):
    beta_member = make_member(beta, role_member, "member-beta-header@example.com")

    response = _available(client_as, beta_member, acme)

    assert response.status_code == 403
    assert response.json()["code"] == "org_membership_required"


def test_a_superadmin_who_is_not_a_member_gets_an_empty_list(client_as, superadmin, acme, weather_in_acme):
    response = _available(client_as, superadmin, acme)

    assert response.status_code == 200
    assert response.json() == []


def test_a_superadmin_who_is_a_member_gets_their_role_s_plugins(client_as, superadmin, role_member, acme, weather_in_acme):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_member)

    assert [plugin["identifier"] for plugin in _available(client_as, superadmin, acme).json()] == ["weather"]


def test_a_superadmin_naming_an_unknown_organization_is_not_found(client_as, superadmin, weather_in_acme):
    client = client_as(superadmin)
    client.credentials(HTTP_X_ORGANIZATION_ID="999999")

    response = client.get(AVAILABLE_URL)

    assert response.status_code == 404
    assert response.json()["code"] == "organization_not_found"


@pytest.mark.parametrize("state", [PluginState.UPLOADED, PluginState.MAINTENANCE, PluginState.FAILED])
def test_a_plugin_that_is_not_running_is_hidden(client_as, member_only, acme, weather_in_acme, state):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=state)

    assert _available(client_as, member_only, acme).json() == []


@pytest.mark.parametrize("state", [GrantState.SUSPENDED, GrantState.GRANTING, GrantState.INSTALL_FAILED])
def test_a_grant_that_is_not_active_hides_the_plugin(client_as, member_only, acme, running_plugin, grant_to, state):
    grant_to(running_plugin(), acme, state=state)

    assert _available(client_as, member_only, acme).json() == []


def test_a_running_plugin_without_a_grant_is_hidden(client_as, member_only, acme, running_plugin):
    running_plugin()

    assert _available(client_as, member_only, acme).json() == []


def test_plugins_are_sorted_by_name(client_as, member_only, acme, running_plugin, grant_to):
    for identifier, name in (("zeta", "Zeta"), ("alpha", "alpha"), ("mid", "Mid")):
        grant_to(running_plugin(id=identifier, name=name), acme)

    assert [plugin["name"] for plugin in _available(client_as, member_only, acme).json()] == ["alpha", "Mid", "Zeta"]


def test_the_list_runs_a_fixed_number_of_queries(client_as, member_only, acme, running_plugin, grant_to, django_assert_max_num_queries):
    for identifier in ("one", "two", "three"):
        grant_to(running_plugin(id=identifier), acme)
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    with django_assert_max_num_queries(3):
        response = client.get(AVAILABLE_URL)

    assert len(response.json()) == 3


def test_a_member_s_api_key_sees_what_the_member_sees(issue_api_key, member_only, acme, weather_in_acme):
    raw_key, _ = issue_api_key(user=member_only)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

    assert [plugin["identifier"] for plugin in client.get(AVAILABLE_URL).json()] == ["weather"]


def test_the_system_key_gets_an_empty_list(issue_api_key, acme, weather_in_acme):
    raw_key, _ = issue_api_key()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

    assert client.get(AVAILABLE_URL).json() == []


def test_the_organization_header_is_required(client_as, member_only, weather_in_acme):
    response = client_as(member_only).get(AVAILABLE_URL)

    assert response.status_code == 400
    assert response.json()["code"] == "org_context_required"


def test_anonymous_callers_must_log_in(anonymous_client, acme):
    anonymous_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    assert anonymous_client.get(AVAILABLE_URL).status_code == 401
