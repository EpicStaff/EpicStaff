"""What the gateway answers while a plugin, or an organization, is being upgraded."""

import pytest
from django.core.cache import cache
from plugins.identity.plugin_login_tokens import issue_plugin_login_token
from plugins.models import GrantState, Plugin, PluginGrant, PluginState
from rbac.models import OrganizationUser

from tests.plugins_tests.conftest import GATEWAY_SECRET, mark_running

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root", "gateway_in_request_thread"),
]

CHECK_URL = "/api/plugin-gateway/check/"


@pytest.fixture(autouse=True)
def gateway_state(settings):
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    cache.delete_pattern("plugins:gw:person:*")
    cache.delete_pattern("plugins:gateway:public-rate:*")
    yield
    cache.delete_pattern("plugins:gw:person:*")
    cache.delete_pattern("plugins:gateway:public-rate:*")


@pytest.fixture
def weather(backend_plugin):
    return mark_running(backend_plugin())


@pytest.fixture
def grant(weather, grant_to, acme):
    return grant_to(weather, acme)


def _check(client, uri, token=None):
    meta = {
        "HTTP_X_PLUGIN_GATEWAY_SECRET": GATEWAY_SECRET,
        "HTTP_X_PLUGIN_IDENTIFIER": "weather",
        "HTTP_X_ORIGINAL_METHOD": "GET",
        "HTTP_X_ORIGINAL_URI": uri,
        "HTTP_X_ORIGINAL_NORMALIZED_PATH": uri,
        "HTTP_X_ORIGINAL_CONTENT_LENGTH": "",
        "HTTP_X_ORIGINAL_TRANSFER_ENCODING": "",
        "HTTP_X_REAL_IP": "203.0.113.7",
    }
    if token is not None:
        meta["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    response = client.get(CHECK_URL, **meta)
    return response.status_code, response.headers.get("X-Plugin-Deny")


def _token(user, organization, grant):
    return issue_plugin_login_token(user=user, org_id=organization.pk, grant_id=grant.pk, identifier="weather").token


def test_a_plugin_in_maintenance_answers_maintenance_on_every_path_public_ones_included(
    weather, grant, member_only, acme, anonymous_client
):
    token = _token(member_only, acme, grant)
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.MAINTENANCE)

    assert _check(anonymous_client, "/api/ping") == (403, "maintenance")
    assert _check(anonymous_client, "/api/whoami") == (403, "maintenance")
    assert _check(anonymous_client, "/api/whoami", token) == (403, "maintenance")


def test_maintenance_comes_before_the_login_check(weather, anonymous_client):
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.MAINTENANCE)

    assert _check(anonymous_client, "/api/whoami", "not-a-token") == (403, "maintenance")


def test_while_the_upgrade_is_prepared_the_plugin_answers_as_usual(weather, grant, member_only, acme, anonymous_client):
    assert _check(anonymous_client, "/api/ping")[0] == 200
    assert _check(anonymous_client, "/api/whoami", _token(member_only, acme, grant))[0] == 200


def test_a_person_of_an_organization_still_upgrading_is_told_maintenance(weather, grant, member_only, acme, anonymous_client):
    token = _token(member_only, acme, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADING)

    assert _check(anonymous_client, "/api/whoami", token) == (403, "maintenance")
    assert _check(anonymous_client, "/api/ping")[0] == 200


def test_a_person_of_an_organization_whose_upgrade_failed_is_told_unavailable(weather, grant, member_only, acme, anonymous_client):
    token = _token(member_only, acme, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADE_FAILED)

    assert _check(anonymous_client, "/api/whoami", token) == (403, "unavailable")


@pytest.mark.parametrize("state", [GrantState.SUSPENDED, GrantState.GRANTING, GrantState.INSTALL_FAILED, GrantState.PURGING])
def test_other_unusable_grants_still_need_a_new_login(weather, grant, member_only, acme, anonymous_client, state):
    token = _token(member_only, acme, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=state)

    assert _check(anonymous_client, "/api/whoami", token) == (401, "login")


def test_another_organization_s_upgrade_does_not_change_this_one_s_answer(
    weather, grant, member_only, acme, beta, grant_to, anonymous_client
):
    grant_to(weather, beta, state=GrantState.UPGRADING)

    assert _check(anonymous_client, "/api/whoami", _token(member_only, acme, grant))[0] == 200


def test_a_deactivated_person_is_refused_before_the_organization_s_upgrade_is_told(
    weather, grant, member_only, acme, anonymous_client
):
    token = _token(member_only, acme, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADING)
    member_only.is_active = False
    member_only.save(update_fields=["is_active"])

    assert _check(anonymous_client, "/api/whoami", token) == (401, "login")


@pytest.mark.parametrize("state", [GrantState.UPGRADING, GrantState.UPGRADE_FAILED])
def test_someone_no_longer_a_member_learns_nothing_of_the_organization_s_upgrade(
    weather, grant, member_only, acme, anonymous_client, state
):
    token = _token(member_only, acme, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=state)
    OrganizationUser.objects.filter(user=member_only, org=acme).delete()

    assert _check(anonymous_client, "/api/whoami", token) == (403, "forbidden")


def test_someone_of_a_deactivated_organization_learns_nothing_of_its_upgrade(
    weather, grant, member_only, acme, anonymous_client
):
    token = _token(member_only, acme, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADING)
    acme.is_active = False
    acme.save(update_fields=["is_active"])

    assert _check(anonymous_client, "/api/whoami", token) == (403, "forbidden")


@pytest.mark.parametrize("state", [GrantState.SUSPENDED, GrantState.PURGING])
def test_someone_no_longer_a_member_of_an_organization_whose_grant_is_suspended_is_forbidden(
    weather, grant, member_only, acme, anonymous_client, state
):
    token = _token(member_only, acme, grant)
    PluginGrant.objects.filter(pk=grant.pk).update(state=state)
    OrganizationUser.objects.filter(user=member_only, org=acme).delete()

    assert _check(anonymous_client, "/api/whoami", token) == (403, "forbidden")
