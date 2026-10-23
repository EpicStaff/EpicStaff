"""Which plugins a person may open in an organization (`available`)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.models import GrantState, Plugin, PluginDevelopmentTarget, PluginGrant, PluginRolePermission, PluginState
from rbac.governance.roles import RoleManagementService
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rest_framework.test import APIClient

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import (
    GATED_NAVIGATION,
    SETTINGS_PERMISSIONS,
    build_package,
    menu_manifest,
    menu_spa,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

AVAILABLE_URL = "/api/plugins/available/"

EDITABLE_PERMISSIONS = [
    {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
    {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]


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
            "description": "Forecasts for the places your organization cares about.",
            "icon_url": "/api/plugin-public/weather/icon/?v=0.1.0",
            "frame_origin": "http://weather.plugins.epicstaff.localhost",
            "permissions": ["read"],
            "availability": "ready",
            "development": False,
            "navigation": [],
        }
    ]


MENU = [
    {"label": "Forecast", "path": "/", "icon_url": "/api/plugin-public/weather/icons/forecast.svg/?v=0.1.0"},
    {"label": "Places", "path": "/places", "icon_url": "/api/plugin-public/weather/icons/places.png/?v=0.1.0"},
    {"label": "Saved places", "path": "/places/saved", "icon_url": "/api/plugin-public/weather/icons/forecast.svg/?v=0.1.0"},
]


@pytest.fixture
def weather_with_a_menu_in_acme(running_plugin, grant_to, acme):
    plugin = running_plugin(spa=menu_spa())
    grant_to(plugin, acme)
    return plugin


def test_the_app_menu_is_listed_in_the_manifest_s_order(client_as, member_only, acme, weather_with_a_menu_in_acme):
    [listed] = _available(client_as, member_only, acme).json()

    assert listed["navigation"] == MENU


def test_the_menu_stays_while_the_plugin_is_stopped_for_an_upgrade(client_as, member_only, acme, weather_with_a_menu_in_acme):
    Plugin.objects.filter(pk=weather_with_a_menu_in_acme.pk).update(state=PluginState.MAINTENANCE)

    [listed] = _available(client_as, member_only, acme).json()

    assert (listed["availability"], listed["navigation"]) == ("maintenance", MENU)


def test_the_menu_name_and_description_follow_the_running_version_not_a_pending_one(
    client_as, member_only, acme, weather_with_a_menu_in_acme, installation, superadmin
):
    newer = menu_manifest([{"label": "Alerts", "path": "/alerts", "icon": "icons/alerts.svg"}], version="0.2.0", description="Alerts only.")
    data = build_package(manifest=newer)
    installation.upload(upload_file(data), len(data), superadmin)

    [listed] = _available(client_as, member_only, acme).json()

    assert (listed["description"], listed["navigation"]) == ("Forecasts for the places your organization cares about.", MENU)


# ---- menu entries gated on a permission ----


FORECAST_ENTRY = {"label": "Forecast", "path": "/", "icon_url": "/api/plugin-public/weather/icons/forecast.svg/?v=0.1.0"}
SETTINGS_ENTRY = {"label": "Organization settings", "path": "/settings", "icon_url": "/api/plugin-public/weather/icons/settings.svg/?v=0.1.0"}


def _gated_weather(running_plugin):
    return running_plugin(spa=menu_spa(GATED_NAVIGATION), user_permissions=SETTINGS_PERMISSIONS)


@pytest.fixture
def weather_with_a_gated_menu_in_acme(running_plugin, grant_to, acme):
    plugin = _gated_weather(running_plugin)
    grant_to(plugin, acme)
    return plugin


def test_a_member_without_an_entry_s_permission_does_not_get_that_entry(client_as, member_only, acme, weather_with_a_gated_menu_in_acme):
    [listed] = _available(client_as, member_only, acme).json()

    assert (listed["permissions"], listed["navigation"]) == (["read"], [FORECAST_ENTRY])


def test_an_org_admin_holding_an_entry_s_permission_gets_that_entry(client_as, admin_acme, acme, weather_with_a_gated_menu_in_acme):
    [listed] = _available(client_as, admin_acme, acme).json()

    assert (listed["permissions"], listed["navigation"]) == (["read", "delete"], [FORECAST_ENTRY, SETTINGS_ENTRY])


@pytest.mark.parametrize(
    ("actions", "labels"),
    [(("read",), ["Forecast"]), (("read", "delete"), ["Forecast", "Organization settings"])],
    ids=["read only", "read and delete"],
)
def test_a_custom_role_gets_the_entries_of_the_actions_ticked_for_it(client_as, make_member, make_custom_role, acme, running_plugin, grant_to, actions, labels):
    grant = grant_to(_gated_weather(running_plugin), acme)
    role = make_custom_role(acme, "Forecasters")
    _store_actions(grant, role, *actions)
    forecaster = make_member(acme, role, "gated-forecaster@example.com")

    [listed] = _available(client_as, forecaster, acme).json()

    assert (listed["permissions"], [entry["label"] for entry in listed["navigation"]]) == (list(actions), labels)


def test_an_entry_follows_the_permission_held_in_the_active_organization_not_another(
    client_as, make_member, role_member, role_org_admin, acme, beta, running_plugin, grant_to
):
    plugin = _gated_weather(running_plugin)
    grant_to(plugin, acme)
    grant_to(plugin, beta)
    person = make_member(beta, role_org_admin, "admin-in-beta-member-in-acme@example.com")
    OrganizationUser.objects.create(user=person, org=acme, role=role_member)

    in_acme = _available(client_as, person, acme).json()[0]["navigation"]
    in_beta = _available(client_as, person, beta).json()[0]["navigation"]

    assert (in_acme, in_beta) == ([FORECAST_ENTRY], [FORECAST_ENTRY, SETTINGS_ENTRY])


def test_an_org_admin_of_another_organization_gets_nothing_of_a_gated_menu(
    client_as, make_member, role_org_admin, admin_acme, acme, beta, weather_with_a_gated_menu_in_acme
):
    beta_admin = make_member(beta, role_org_admin, "admin-beta-gated@example.com")

    response = _available(client_as, beta_admin, beta)

    assert response.status_code == 200
    assert response.json() == []
    # The gated entry is there: an Org Admin of the plugin's own organization gets it.
    assert _available(client_as, admin_acme, acme).json()[0]["navigation"] == [FORECAST_ENTRY, SETTINGS_ENTRY]


def test_an_org_admin_sees_the_plugin(client_as, admin_acme, acme, weather_in_acme):
    assert [plugin["identifier"] for plugin in _available(client_as, admin_acme, acme).json()] == ["weather"]


def test_a_viewer_without_the_default_view_sees_nothing(client_as, make_member, role_viewer, acme, weather_in_acme):
    viewer = make_member(acme, role_viewer, "viewer-plugins@example.com")

    response = _available(client_as, viewer, acme)

    assert response.status_code == 200
    assert response.json() == []


def test_a_custom_role_without_plugin_actions_gets_nothing_even_with_every_epicstaff_permission(client_as, make_member, acme, weather_in_acme):
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


def test_a_member_of_another_organization_gets_nothing_of_it(client_as, make_member, role_member, member_only, acme, beta, weather_with_a_menu_in_acme):
    beta_member = make_member(beta, role_member, "member-beta-plugins@example.com")

    response = _available(client_as, beta_member, beta)

    assert response.status_code == 200
    assert response.json() == []
    # The plugin and its menu are there: a member of its own organization sees both.
    assert _available(client_as, member_only, acme).json()[0]["navigation"] == MENU


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


@pytest.mark.parametrize("state", [PluginState.UPLOADED, PluginState.FAILED])
def test_a_plugin_that_is_not_running_is_hidden(client_as, member_only, acme, weather_in_acme, state):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=state)

    assert _available(client_as, member_only, acme).json() == []


def test_a_plugin_stopped_for_an_upgrade_stays_listed_in_maintenance(client_as, member_only, acme, weather_in_acme):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.MAINTENANCE)

    [listed] = _available(client_as, member_only, acme).json()

    assert (listed["identifier"], listed["availability"]) == ("weather", "maintenance")


def test_an_organization_still_upgrading_lists_the_plugin_in_maintenance(client_as, member_only, acme, weather_in_acme):
    PluginGrant.objects.filter(plugin=weather_in_acme, org=acme).update(state=GrantState.UPGRADING)

    [listed] = _available(client_as, member_only, acme).json()

    assert listed["availability"] == "maintenance"


def test_an_organization_whose_upgrade_failed_does_not_list_the_plugin(client_as, member_only, acme, weather_in_acme):
    PluginGrant.objects.filter(plugin=weather_in_acme, org=acme).update(state=GrantState.UPGRADE_FAILED)

    assert _available(client_as, member_only, acme).json() == []


def test_another_organization_s_upgrade_does_not_change_this_one_s_listing(
    client_as, member_only, acme, beta, weather_in_acme, grant_to
):
    grant_to(weather_in_acme, beta, state=GrantState.UPGRADING)

    [listed] = _available(client_as, member_only, acme).json()

    assert listed["availability"] == "ready"


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
    # With app menus gated on a permission: the menu comes from the manifest the list already
    # loads, and the entries are filtered by the actions the list already resolved.
    for identifier in ("one", "two", "three"):
        grant_to(running_plugin(id=identifier, spa=menu_spa(GATED_NAVIGATION), user_permissions=SETTINGS_PERMISSIONS), acme)
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    with django_assert_max_num_queries(3):
        response = client.get(AVAILABLE_URL)

    assert [[entry["label"] for entry in plugin["navigation"]] for plugin in response.json()] == [["Forecast"]] * 3


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


def _store_actions(grant, role, *actions):
    bits = 0
    for action in actions:
        bits |= int(Permission[action.upper()])
    return PluginRolePermission.objects.create(grant=grant, role=role, permissions=bits)


def test_a_custom_role_with_view_lists_the_plugin(client_as, make_member, make_custom_role, acme, running_plugin, grant_to):
    grant = grant_to(running_plugin(user_permissions=EDITABLE_PERMISSIONS), acme)
    role = make_custom_role(acme, "Forecasters")
    _store_actions(grant, role, "read", "update")
    forecaster = make_member(acme, role, "forecaster@example.com")

    response = _available(client_as, forecaster, acme)

    assert response.status_code == 200
    assert [(plugin["identifier"], plugin["permissions"]) for plugin in response.json()] == [("weather", ["read", "update"])]


def test_a_custom_role_with_actions_but_no_view_does_not_list_the_plugin(client_as, make_member, make_custom_role, acme, running_plugin, grant_to):
    grant = grant_to(running_plugin(user_permissions=EDITABLE_PERMISSIONS), acme)
    role = make_custom_role(acme, "Editors without view")
    _store_actions(grant, role, "update")
    editor = make_member(acme, role, "editor-no-view@example.com")

    assert _available(client_as, editor, acme).json() == []


def test_actions_stored_for_a_grant_in_one_organization_never_apply_in_another(client_as, make_member, make_custom_role, acme, beta, running_plugin, grant_to):
    plugin = running_plugin()
    acme_role = make_custom_role(acme, "Forecasters")
    _store_actions(grant_to(plugin, acme), acme_role, "read")
    grant_to(plugin, beta)
    person = make_member(acme, acme_role, "two-orgs@example.com")
    OrganizationUser.objects.create(user=person, org=beta, role=make_custom_role(beta, "Forecasters"))

    assert [plugin["identifier"] for plugin in _available(client_as, person, acme).json()] == ["weather"]
    assert _available(client_as, person, beta).json() == []


def test_a_custom_role_lists_through_a_fixed_number_of_queries(client_as, make_member, make_custom_role, acme, running_plugin, grant_to, django_assert_max_num_queries):
    role = make_custom_role(acme, "Forecasters")
    for identifier in ("one", "two", "three"):
        _store_actions(grant_to(running_plugin(id=identifier), acme), role, "read")
    client = client_as(make_member(acme, role, "forecaster-queries@example.com"))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    # One more than a built-in role: the custom role's stored actions, all in one query.
    with django_assert_max_num_queries(4):
        response = client.get(AVAILABLE_URL)

    assert len(response.json()) == 3


def test_deleting_the_role_deletes_its_plugin_actions(admin_acme, make_custom_role, acme, running_plugin, grant_to):
    role = make_custom_role(acme, "Forecasters")
    _store_actions(grant_to(running_plugin(), acme), role, "read")

    RoleManagementService().delete_role(actor=admin_acme, role_id=role.pk)

    assert not PluginRolePermission.objects.exists()


def test_deleting_the_grant_deletes_the_role_s_plugin_actions(make_custom_role, acme, running_plugin, grant_to):
    grant = grant_to(running_plugin(), acme)
    _store_actions(grant, make_custom_role(acme, "Forecasters"), "read")

    PluginGrant.objects.filter(pk=grant.pk).delete()

    assert not PluginRolePermission.objects.exists()



# ---- plugin development mode: members see only that a plugin is in development ----


def _development_of(client_as, user, organization):
    return [plugin["development"] for plugin in _available(client_as, user, organization).json()]


def test_a_plugin_is_in_development_only_while_the_mode_is_on_and_a_target_is_stored(
    client_as, member_only, acme, weather_in_acme, settings
):
    settings.PLUGINS_DEV_MODE = True
    without_target = _development_of(client_as, member_only, acme)
    PluginDevelopmentTarget.objects.create(plugin=weather_in_acme, spa_port=5173)
    with_target = _development_of(client_as, member_only, acme)
    settings.PLUGINS_DEV_MODE = False
    mode_off = _development_of(client_as, member_only, acme)

    assert (without_target, with_target, mode_off) == ([False], [True], [False])


def test_a_port_for_a_part_the_package_lacks_is_not_development(client_as, member_only, acme, weather_in_acme, settings):
    settings.PLUGINS_DEV_MODE = True
    PluginDevelopmentTarget.objects.create(plugin=weather_in_acme, backend_port=8001)

    assert _development_of(client_as, member_only, acme) == [False]


def test_a_plugin_stopped_for_an_upgrade_is_not_in_development(client_as, member_only, acme, weather_in_acme, settings):
    settings.PLUGINS_DEV_MODE = True
    PluginDevelopmentTarget.objects.create(plugin=weather_in_acme, spa_port=5173)
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.MAINTENANCE)

    listed = _available(client_as, member_only, acme).json()

    assert [(plugin["availability"], plugin["development"]) for plugin in listed] == [("maintenance", False)]


def test_a_plugin_whose_organization_still_upgrades_is_not_in_development(
    client_as, member_only, acme, weather_in_acme, settings
):
    settings.PLUGINS_DEV_MODE = True
    PluginDevelopmentTarget.objects.create(plugin=weather_in_acme, spa_port=5173)
    PluginGrant.objects.filter(plugin=weather_in_acme, org=acme).update(state=GrantState.UPGRADING)

    listed = _available(client_as, member_only, acme).json()

    assert [(plugin["availability"], plugin["development"]) for plugin in listed] == [("maintenance", False)]


@pytest.mark.parametrize("state", [PluginState.PROVISIONING, PluginState.FAILED, PluginState.MAINTENANCE])
def test_a_plugin_that_is_not_running_is_never_served_from_development(weather_in_acme, settings, state):
    from plugins.development.development_targets import served_from_development

    settings.PLUGINS_DEV_MODE = True
    PluginDevelopmentTarget.objects.create(plugin=weather_in_acme, spa_port=5173)
    plugin = Plugin.objects.select_related("current_package", "development_target").get(pk=weather_in_acme.pk)
    running = served_from_development(plugin)
    plugin.state = state

    assert (running, served_from_development(plugin)) == (True, False)


def test_a_member_never_sees_the_ports(client_as, member_only, acme, weather_in_acme, settings):
    settings.PLUGINS_DEV_MODE = True
    PluginDevelopmentTarget.objects.create(plugin=weather_in_acme, spa_port=5173)

    plugin = _available(client_as, member_only, acme).json()[0]

    assert plugin["development"] is True
    assert "5173" not in str(plugin)
    assert not {"backend_port", "spa_port", "target", "host_address"} & set(plugin)


def test_a_member_of_another_organization_still_gets_nothing_of_a_plugin_in_development(
    client_as, make_member, role_member, beta, weather_in_acme, settings
):
    settings.PLUGINS_DEV_MODE = True
    PluginDevelopmentTarget.objects.create(plugin=weather_in_acme, spa_port=5173)
    beta_member = make_member(beta, role_member, "member-beta-development@example.com")

    assert _available(client_as, beta_member, beta).json() == []


def test_development_adds_no_query_whatever_the_number_of_plugins(client_as, member_only, acme, running_plugin, grant_to, settings):
    settings.PLUGINS_DEV_MODE = True
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    counts = []
    for identifier in ("one", "two", "three", "four", "five"):
        plugin = running_plugin(id=identifier)
        grant_to(plugin, acme)
        PluginDevelopmentTarget.objects.create(plugin=plugin, spa_port=5173)
        if identifier in ("one", "five"):
            with CaptureQueriesContext(connection) as queries:
                assert all(item["development"] for item in client.get(AVAILABLE_URL).json())
            counts.append(len(queries))

    assert counts[0] == counts[1] <= 3
