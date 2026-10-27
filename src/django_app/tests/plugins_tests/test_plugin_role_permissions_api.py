"""The plugin rows of the Roles matrix: rows for an organization, a role's actions, and writes."""

import pytest
from plugins.models import GrantState, Plugin, PluginRolePermission, PluginState
from rbac.models import OrganizationUser
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from rest_framework.test import APIClient

from tests.plugins_tests.conftest import ROLE_MANAGER_PERMISSIONS

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

ROWS_URL = "/api/admin/plugin-role-permissions/rows/"

EDITABLE_PERMISSIONS = [
    {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
    {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
    {"action": "delete", "description": "Change settings.", "defaults": {"org_admin": True, "member": False, "viewer": False}},
]
ALL_ACTIONS = ["read", "update", "delete"]


def _role_url(role):
    return f"/api/admin/plugin-role-permissions/{role.pk}/"


def _store_actions(grant, role, *actions):
    bits = 0
    for action in actions:
        bits |= int(Permission[action.upper()])
    return PluginRolePermission.objects.create(grant=grant, role=role, permissions=bits)


def _put(client, role, *entries):
    body = {"plugins": [{"plugin_identifier": identifier, "actions": list(actions)} for identifier, actions in entries]}
    return client.put(_role_url(role), body, format="json")


def _granted(response):
    return {row["plugin_identifier"]: row["granted"] for row in response.json()["rows"]}


def _error_locs(response):
    return [error["loc"] for error in response.json()["errors"]]


@pytest.fixture
def weather(running_plugin):
    return running_plugin(user_permissions=EDITABLE_PERMISSIONS)


@pytest.fixture
def weather_grant(weather, grant_to, acme):
    return grant_to(weather, acme)


@pytest.fixture
def forecasters(make_custom_role, acme):
    return make_custom_role(acme, "Forecasters")


@pytest.fixture
def role_manager(make_custom_role, make_member, acme):
    """A member of Acme who manages roles but holds only View on Weather."""
    role = make_custom_role(acme, "Role managers", ROLE_MANAGER_PERMISSIONS)
    return make_member(acme, role, "role-manager@example.com"), role


@pytest.fixture
def admin_beta(make_member, role_org_admin, beta):
    return make_member(beta, role_org_admin, "admin-beta-plugins@example.com")


# ---- rows for an organization ----


def test_rows_list_running_plugins_with_an_active_grant_in_the_organization(client_as, admin_acme, acme, beta, weather_grant, running_plugin, grant_to):
    running_plugin(id="ungranted")
    grant_to(running_plugin(id="elsewhere"), beta)
    grant_to(running_plugin(id="suspended"), acme, state=GrantState.SUSPENDED)
    stopped = running_plugin(id="stopped")
    grant_to(stopped, acme)
    Plugin.objects.filter(pk=stopped.pk).update(state=PluginState.FAILED)

    response = client_as(admin_acme).get(ROWS_URL, {"org_id": acme.id})

    assert response.status_code == 200
    assert response.json() == {
        "organization": {"id": acme.id, "name": acme.name},
        "rows": [
            {
                "plugin_identifier": "weather",
                "name": "Weather",
                "icon_url": "/api/plugin-public/weather/icon/?v=0.1.0",
                "actions": [
                    {"action": "read", "label": "View", "description": "Open it."},
                    {"action": "update", "label": "Edit", "description": "Edit places."},
                    {"action": "delete", "label": "Delete", "description": "Change settings."},
                ],
                "ceiling": ALL_ACTIONS,
            }
        ],
    }


def test_rows_are_sorted_by_name(client_as, admin_acme, acme, running_plugin, grant_to):
    for identifier, name in (("zeta", "Zeta"), ("alpha", "alpha"), ("mid", "Mid")):
        grant_to(running_plugin(id=identifier, name=name), acme)

    response = client_as(admin_acme).get(ROWS_URL, {"org_id": acme.id})

    assert [row["name"] for row in response.json()["rows"]] == ["alpha", "Mid", "Zeta"]


def test_the_ceiling_is_the_caller_s_own_actions_in_the_organization(client_as, acme, weather_grant, role_manager):
    manager, manager_role = role_manager
    _store_actions(weather_grant, manager_role, "read")

    response = client_as(manager).get(ROWS_URL, {"org_id": acme.id})

    assert response.json()["rows"][0]["ceiling"] == ["read"]


def test_a_superadmin_s_ceiling_is_every_action(client_as, superadmin, acme, weather_grant):
    response = client_as(superadmin).get(ROWS_URL, {"org_id": acme.id})

    assert response.json()["rows"][0]["ceiling"] == ALL_ACTIONS


def test_the_ceiling_is_empty_for_a_caller_who_cannot_update_roles(client_as, make_custom_role, make_member, acme, weather_grant):
    reader = make_member(acme, make_custom_role(acme, "Role readers", {ResourceType.ROLES.value: ["read"]}), "role-reader@example.com")

    response = client_as(reader).get(ROWS_URL, {"org_id": acme.id})

    assert response.status_code == 200
    assert response.json()["rows"][0]["ceiling"] == []


def test_rows_of_another_organization_are_not_found(client_as, admin_acme, beta, running_plugin, grant_to):
    grant_to(running_plugin(), beta)

    response = client_as(admin_acme).get(ROWS_URL, {"org_id": beta.id})

    assert response.status_code == 404
    assert response.json()["code"] == "organization_not_found"


def test_rows_of_an_unknown_organization_are_not_found(client_as, superadmin):
    response = client_as(superadmin).get(ROWS_URL, {"org_id": 999999})

    assert response.status_code == 404
    assert response.json()["code"] == "organization_not_found"


def test_rows_need_an_organization(client_as, admin_acme):
    response = client_as(admin_acme).get(ROWS_URL)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"


def test_a_member_who_cannot_read_roles_is_refused(client_as, member_only, acme, weather_grant):
    response = client_as(member_only).get(ROWS_URL, {"org_id": acme.id})

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


# ---- a custom role ----


def test_a_custom_role_shows_its_stored_actions(client_as, admin_acme, acme, weather_grant, forecasters):
    _store_actions(weather_grant, forecasters, "read", "update")

    response = client_as(admin_acme).get(_role_url(forecasters), {"org_id": 999999})

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == {"id": forecasters.pk, "name": "Forecasters", "is_built_in": False, "org_id": acme.id}
    assert body["organization"] == {"id": acme.id, "name": acme.name}
    assert body["editable"] is True
    assert [(row["plugin_identifier"], row["granted"], row["ceiling"]) for row in body["rows"]] == [
        ("weather", ["read", "update"], ALL_ACTIONS)
    ]


def test_a_custom_role_without_stored_actions_has_none(client_as, admin_acme, weather_grant, forecasters):
    assert _granted(client_as(admin_acme).get(_role_url(forecasters))) == {"weather": []}


def test_writing_a_custom_role_round_trips(client_as, admin_acme, weather_grant, forecasters):
    client = client_as(admin_acme)

    written = _put(client, forecasters, ("weather", ["read", "update"]))

    assert written.status_code == 200
    assert _granted(written) == {"weather": ["read", "update"]}
    assert _granted(client.get(_role_url(forecasters))) == {"weather": ["read", "update"]}
    stored = PluginRolePermission.objects.get(grant=weather_grant, role=forecasters)
    assert stored.permissions == int(Permission.READ | Permission.UPDATE)
    assert stored.updated_by == admin_acme


def test_a_write_replaces_every_usable_plugin_of_the_organization(client_as, admin_acme, acme, weather_grant, forecasters, running_plugin, grant_to):
    radar_grant = grant_to(running_plugin(id="radar", name="Radar"), acme)
    _store_actions(weather_grant, forecasters, "read", "update")
    _store_actions(radar_grant, forecasters, "read")

    response = _put(client_as(admin_acme), forecasters, ("radar", ["read"]))

    assert _granted(response) == {"radar": ["read"], "weather": []}
    assert list(PluginRolePermission.objects.values_list("grant_id", flat=True)) == [radar_grant.pk]


def test_an_empty_write_clears_every_action(client_as, admin_acme, weather_grant, forecasters):
    _store_actions(weather_grant, forecasters, "read")

    response = client_as(admin_acme).put(_role_url(forecasters), {"plugins": []}, format="json")

    assert response.status_code == 200
    assert not PluginRolePermission.objects.exists()


def test_a_write_leaves_the_actions_of_a_suspended_grant_alone(client_as, admin_acme, acme, weather_grant, forecasters, running_plugin, grant_to):
    suspended = grant_to(running_plugin(id="radar"), acme, state=GrantState.SUSPENDED)
    _store_actions(suspended, forecasters, "read")

    _put(client_as(admin_acme), forecasters, ("weather", ["read"]))

    assert PluginRolePermission.objects.filter(grant=suspended).exists()


def test_a_write_is_logged_per_changed_plugin(client_as, admin_acme, weather_grant, forecasters, mocker):
    info = mocker.patch("plugins.audit.logger.info")

    _put(client_as(admin_acme), forecasters, ("weather", ["read", "update"]))

    info.assert_called_once()
    assert info.call_args.kwargs["identifier"] == "weather"
    assert (info.call_args.kwargs["after"], info.call_args.kwargs["before"]) == ("read,update", "none")


def test_an_action_outside_the_caller_s_ceiling_is_refused(client_as, weather_grant, forecasters, role_manager):
    manager, manager_role = role_manager
    _store_actions(weather_grant, manager_role, "read")

    response = _put(client_as(manager), forecasters, ("weather", ["read", "update"]))

    assert response.status_code == 403
    assert response.json()["code"] == "permission_escalation_denied"
    assert not PluginRolePermission.objects.filter(role=forecasters).exists()


def test_an_unchanged_action_above_the_ceiling_does_not_block_a_change_elsewhere(client_as, acme, weather_grant, forecasters, role_manager, running_plugin, grant_to):
    radar_grant = grant_to(running_plugin(id="radar", name="Radar"), acme)
    manager, manager_role = role_manager
    _store_actions(weather_grant, manager_role, "read")
    _store_actions(radar_grant, manager_role, "read")
    _store_actions(weather_grant, forecasters, "read", "update", "delete")

    response = _put(client_as(manager), forecasters, ("weather", ["read", "update", "delete"]), ("radar", ["read"]))

    assert response.status_code == 200
    assert _granted(response) == {"radar": ["read"], "weather": ["read", "update", "delete"]}


@pytest.mark.parametrize(
    "entries",
    [[("weather", ["read"])], []],
    ids=["removed from the list of actions", "plugin left out of the write"],
)
def test_removing_an_action_above_the_ceiling_is_refused(client_as, weather_grant, forecasters, role_manager, entries):
    manager, manager_role = role_manager
    _store_actions(weather_grant, manager_role, "read")
    _store_actions(weather_grant, forecasters, "read", "update")

    response = _put(client_as(manager), forecasters, *entries)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_escalation_denied"
    assert _granted(client_as(manager).get(_role_url(forecasters))) == {"weather": ["read", "update"]}


def test_removing_an_action_within_the_ceiling_is_allowed(client_as, weather_grant, forecasters, role_manager):
    manager, manager_role = role_manager
    _store_actions(weather_grant, manager_role, "read", "update")
    _store_actions(weather_grant, forecasters, "read", "update")

    response = _put(client_as(manager), forecasters, ("weather", ["read"]))

    assert response.status_code == 200
    assert _granted(response) == {"weather": ["read"]}


def test_actions_within_the_caller_s_ceiling_are_written(client_as, weather_grant, forecasters, role_manager):
    manager, manager_role = role_manager
    _store_actions(weather_grant, manager_role, "read")

    response = _put(client_as(manager), forecasters, ("weather", ["read"]))

    assert response.status_code == 200
    assert _granted(response) == {"weather": ["read"]}


def test_rows_sent_with_no_actions_mean_no_actions(client_as, acme, weather_grant, forecasters, role_manager, running_plugin, grant_to):
    grant_to(running_plugin(id="radar", name="Radar"), acme)
    manager, manager_role = role_manager
    _store_actions(weather_grant, manager_role, "read")
    _store_actions(weather_grant, forecasters, "read")

    response = _put(client_as(manager), forecasters, ("radar", []), ("weather", []))

    assert response.status_code == 200
    assert _granted(response) == {"radar": [], "weather": []}
    assert not PluginRolePermission.objects.filter(role=forecasters).exists()


def test_a_superadmin_may_grant_every_action(client_as, superadmin, weather_grant, forecasters):
    response = _put(client_as(superadmin), forecasters, ("weather", ALL_ACTIONS))

    assert response.status_code == 200
    assert _granted(response) == {"weather": ALL_ACTIONS}


def test_a_caller_who_may_read_but_not_update_roles_sees_a_read_only_role(client_as, make_custom_role, make_member, acme, weather_grant, forecasters):
    reader = make_member(acme, make_custom_role(acme, "Role readers", {ResourceType.ROLES.value: ["read"]}), "role-reader-2@example.com")
    client = client_as(reader)

    shown = client.get(_role_url(forecasters)).json()
    written = _put(client, forecasters, ("weather", ["read"]))

    assert (shown["editable"], shown["rows"][0]["ceiling"]) == (False, [])
    assert written.status_code == 403
    assert written.json()["code"] == "permission_denied"


def test_a_write_without_read_grant_may_still_write(client_as, make_custom_role, make_member, acme, weather_grant, forecasters):
    writer_role = make_custom_role(acme, "Role writers", {ResourceType.ROLES.value: ["update"]})
    _store_actions(weather_grant, writer_role, "read")
    writer = make_member(acme, writer_role, "role-writer@example.com")
    client = client_as(writer)

    written = _put(client, forecasters, ("weather", ["read"]))
    read = client.get(_role_url(forecasters))

    assert written.status_code == 200
    assert _granted(written) == {"weather": ["read"]}
    assert read.status_code == 403


# ---- invalid writes ----


@pytest.mark.parametrize(
    ("entries", "loc"),
    [
        ([("unknown", ["read"])], "plugins[0].plugin_identifier"),
        ([("weather", ["read"]), ("weather", ["read"])], "plugins[1].plugin_identifier"),
        ([("weather", ["read", "export"])], "plugins[0].actions"),
        ([("weather", ["read", "read"])], "plugins[0].actions"),
        ([("weather", ["update"])], "plugins[0].actions"),
        ([("weather", ["frobnicate"])], "plugins[0].actions"),
    ],
    ids=["unknown plugin", "listed twice", "undeclared action", "duplicated action", "no read", "not an action"],
)
def test_an_invalid_write_names_the_problem(client_as, admin_acme, weather_grant, forecasters, entries, loc):
    response = _put(client_as(admin_acme), forecasters, *entries)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_plugin_role_permissions"
    assert loc in _error_locs(response)
    assert not PluginRolePermission.objects.exists()


def test_a_plugin_granted_only_to_another_organization_is_invalid(client_as, admin_acme, beta, forecasters, running_plugin, grant_to):
    grant_to(running_plugin(id="radar"), beta)

    response = _put(client_as(admin_acme), forecasters, ("radar", ["read"]))

    assert response.status_code == 400
    assert _error_locs(response) == ["plugins[0].plugin_identifier"]


@pytest.mark.parametrize("plugin_state", [PluginState.FAILED, PluginState.PROVISIONING])
def test_a_plugin_that_is_not_running_is_invalid(client_as, admin_acme, weather, weather_grant, forecasters, plugin_state):
    Plugin.objects.filter(pk=weather.pk).update(state=plugin_state)

    response = _put(client_as(admin_acme), forecasters, ("weather", ["read"]))

    assert _error_locs(response) == ["plugins[0].plugin_identifier"]


def test_a_malformed_body_is_refused(client_as, admin_acme, forecasters):
    response = client_as(admin_acme).put(_role_url(forecasters), {"plugins": [{"actions": ["read"]}]}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"


# ---- built-in roles ----


def test_a_built_in_role_for_an_organization_shows_the_manifest_defaults_read_only(client_as, admin_acme, acme, role_member, weather_grant):
    response = client_as(admin_acme).get(_role_url(role_member), {"org_id": acme.id})

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == {"id": role_member.pk, "name": BuiltInRole.MEMBER, "is_built_in": True, "org_id": None}
    assert body["organization"] == {"id": acme.id, "name": acme.name}
    assert body["editable"] is False
    assert [(row["plugin_identifier"], row["granted"], row["ceiling"]) for row in body["rows"]] == [
        ("weather", ["read", "update"], [])
    ]


def test_a_built_in_role_without_an_organization_shows_each_plugin_of_the_caller_s_organizations_once(client_as, make_member, role_org_admin, role_viewer, acme, beta, running_plugin, grant_to):
    shared = running_plugin(id="shared", name="Shared")
    grant_to(shared, acme)
    grant_to(shared, beta)
    grant_to(running_plugin(id="acme-only", name="Acme only"), acme)
    grant_to(running_plugin(id="beta-only", name="Beta only"), beta)
    running_plugin(id="ungranted", name="Ungranted")
    admin_of_both = make_member(acme, role_org_admin, "admin-both@example.com")
    OrganizationUser.objects.create(user=admin_of_both, org=beta, role=role_org_admin)

    response = client_as(admin_of_both).get(_role_url(role_viewer))

    assert response.status_code == 200
    assert response.json()["organization"] is None
    assert [row["plugin_identifier"] for row in response.json()["rows"]] == ["acme-only", "beta-only", "shared"]


def test_a_built_in_role_without_an_organization_leaves_out_organizations_the_caller_cannot_read(client_as, admin_acme, role_viewer, acme, beta, running_plugin, grant_to):
    grant_to(running_plugin(id="acme-only"), acme)
    grant_to(running_plugin(id="beta-only"), beta)

    response = client_as(admin_acme).get(_role_url(role_viewer))

    assert [row["plugin_identifier"] for row in response.json()["rows"]] == ["acme-only"]


def test_a_superadmin_sees_every_running_plugin_on_a_built_in_role(client_as, superadmin, role_org_admin, running_plugin):
    running_plugin(user_permissions=EDITABLE_PERMISSIONS)

    response = client_as(superadmin).get(_role_url(role_org_admin))

    assert _granted(response) == {"weather": ALL_ACTIONS}


def test_a_built_in_role_for_another_organization_is_not_found(client_as, admin_acme, role_member, beta):
    response = client_as(admin_acme).get(_role_url(role_member), {"org_id": beta.id})

    assert response.status_code == 404
    assert response.json()["code"] == "organization_not_found"


def test_a_built_in_role_cannot_be_written(client_as, superadmin, role_member, weather_grant):
    response = _put(client_as(superadmin), role_member, ("weather", ["read"]))

    assert response.status_code == 403
    assert response.json()["code"] == "built_in_role_immutable"


# ---- other organizations ----


def test_a_custom_role_of_another_organization_is_not_found(client_as, admin_beta, forecasters):
    response = client_as(admin_beta).get(_role_url(forecasters))

    assert response.status_code == 404
    assert response.json()["code"] == "role_not_found"


def test_writing_a_custom_role_of_another_organization_is_not_found(client_as, admin_beta, weather_grant, forecasters):
    response = _put(client_as(admin_beta), forecasters, ("weather", ["read"]))

    assert response.status_code == 404
    assert response.json()["code"] == "role_not_found"
    assert not PluginRolePermission.objects.exists()


def test_an_unknown_role_is_not_found(client_as, admin_acme):
    response = client_as(admin_acme).get("/api/admin/plugin-role-permissions/999999/")

    assert response.status_code == 404
    assert response.json()["code"] == "role_not_found"


# ---- credentials ----


def test_a_user_api_key_may_read(issue_api_key, admin_acme, acme, weather_grant, forecasters):
    raw_key, _ = issue_api_key(user=admin_acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert client.get(ROWS_URL, {"org_id": acme.id}).status_code == 200
    assert client.get(_role_url(forecasters)).status_code == 200


def test_an_api_key_cannot_write(issue_api_key, admin_acme, weather_grant, forecasters):
    raw_key, _ = issue_api_key(user=admin_acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    response = _put(client, forecasters, ("weather", ["read"]))

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert not PluginRolePermission.objects.exists()


def test_the_system_key_cannot_read(issue_api_key, acme, weather_grant):
    raw_key, _ = issue_api_key()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert client.get(ROWS_URL, {"org_id": acme.id}).status_code == 403


def test_anonymous_callers_must_log_in(anonymous_client, acme):
    assert anonymous_client.get(ROWS_URL, {"org_id": acme.id}).status_code == 401


# ---- query counts ----


@pytest.fixture
def three_plugins_in_acme(running_plugin, grant_to, acme, forecasters):
    for identifier in ("one", "two", "three"):
        _store_actions(grant_to(running_plugin(id=identifier, user_permissions=EDITABLE_PERMISSIONS), acme), forecasters, "read")


def _queries_for(client, url, params, django_assert_max_num_queries, limit):
    with django_assert_max_num_queries(limit) as captured:
        response = client.get(url, params)
    assert response.status_code == 200
    return len(captured.captured_queries)


@pytest.mark.parametrize("caller", ["admin_acme", "role_manager"])
def test_rows_run_a_fixed_number_of_queries(request, client_as, acme, three_plugins_in_acme, running_plugin, grant_to, caller, django_assert_max_num_queries):
    user = request.getfixturevalue(caller)
    user = user[0] if isinstance(user, tuple) else user
    client = client_as(user)
    with_three = _queries_for(client, ROWS_URL, {"org_id": acme.id}, django_assert_max_num_queries, 10)

    for identifier in ("four", "five"):
        grant_to(running_plugin(id=identifier), acme)
    with_five = _queries_for(client, ROWS_URL, {"org_id": acme.id}, django_assert_max_num_queries, 10)

    assert with_five == with_three


def test_a_custom_role_reads_in_a_fixed_number_of_queries(client_as, admin_acme, acme, forecasters, three_plugins_in_acme, running_plugin, grant_to, django_assert_max_num_queries):
    client = client_as(admin_acme)
    with_three = _queries_for(client, _role_url(forecasters), {}, django_assert_max_num_queries, 15)

    for identifier in ("four", "five"):
        grant_to(running_plugin(id=identifier), acme)
    with_five = _queries_for(client, _role_url(forecasters), {}, django_assert_max_num_queries, 15)

    assert with_five == with_three


@pytest.mark.parametrize("org_param", [True, False])
def test_a_built_in_role_reads_in_a_fixed_number_of_queries(client_as, admin_acme, acme, role_member, three_plugins_in_acme, running_plugin, grant_to, org_param, django_assert_max_num_queries):
    client = client_as(admin_acme)
    params = {"org_id": acme.id} if org_param else {}
    with_three = _queries_for(client, _role_url(role_member), params, django_assert_max_num_queries, 15)

    for identifier in ("four", "five"):
        grant_to(running_plugin(id=identifier), acme)
    with_five = _queries_for(client, _role_url(role_member), params, django_assert_max_num_queries, 15)

    assert with_five == with_three
