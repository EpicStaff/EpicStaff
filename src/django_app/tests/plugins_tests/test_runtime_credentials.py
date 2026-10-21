"""The runtime credentials a node fetches for a placement: the runtime file and its revisions."""

from datetime import timedelta

import pytest
from django.utils import timezone
from epicstaff_plugin.contracts.runtime import RuntimeFile
from plugins.identity.signing_keys import PluginSigningKeyService
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.nodes.runtime_credentials_service import RuntimeCredentialsService
from pydantic import ValidationError
from plugins.models import GrantState, PluginGrant, PluginSigningKey
from rbac.models import Organization

from src.shared.models.plugin_nodes import RuntimeCredentials
from tests.plugins_tests.conftest import mark_running, service_account_client
from tests.plugins_tests.package_builder import TOKEN_SETTING, UNITS_SETTING

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
SETTINGS_URL = "/api/admin/plugins/weather/settings/"
NOTE_SETTING = {"key": "note", "type": "string", "label": "Note", "description": "Shown on the page.", "required": False}


def _credentials_url(placement_id):
    return f"/api/plugin-nodes/self/placements/{placement_id}/runtime-credentials/"


def _credentials(node_client, plugin):
    response = node_client.post(_credentials_url(plugin.placement.pk))
    assert response.status_code == 200
    return response


def _desired_placement(node_client):
    return node_client.get(DESIRED_STATE_URL).json()["placements"][0]


@pytest.fixture
def weather(backend_plugin):
    return backend_plugin(settings=[dict(UNITS_SETTING), dict(TOKEN_SETTING), dict(NOTE_SETTING)])


def test_the_runtime_file_holds_what_the_plugin_process_needs(weather, node_client, settings):
    response = _credentials(node_client, weather)

    body = response.json()
    assert response["Cache-Control"] == "no-store"
    assert body["placement_id"] == weather.placement.pk
    assert body["settings_revision"] == 0
    runtime_file = body["runtime_file"]
    assert runtime_file["format"] == 1
    assert runtime_file["plugin"] == {"identifier": "weather", "version": "0.2.0"}
    assert runtime_file["issuer"] == "http://epicstaff.localhost"
    assert runtime_file["public_url"] == "http://weather.plugins.epicstaff.localhost"
    assert runtime_file["epicstaff_public_url"] == "http://epicstaff.localhost"
    assert runtime_file["epicstaff_api_url"] == settings.PLUGINS_INTERNAL_API_URL
    assert runtime_file["service_accounts"] == {}
    assert runtime_file["public_paths"] == [
        {"path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0}
    ]
    assert [key["kid"] for key in runtime_file["jwks"]["keys"]] == [PluginSigningKey.objects.get().kid]


def test_the_node_side_reads_the_document_with_the_shared_model(weather, node_client):
    credentials = RuntimeCredentials.model_validate_json(_credentials(node_client, weather).content, extra="ignore")

    assert credentials.runtime_file.plugin.identifier == "weather"


def test_settings_carry_values_or_defaults_and_leave_out_unset_optional_ones(weather, node_client):
    runtime_file = _credentials(node_client, weather).json()["runtime_file"]

    assert runtime_file["settings"] == {"units": "metric"}
    assert runtime_file["secret_settings"] == {}


def test_stored_values_and_decrypted_secrets_are_handed_over(weather, node_client, superadmin_client):
    superadmin_client.patch(
        SETTINGS_URL, {"values": {"units": "imperial", "note": "hello", "forecast_api_token": "token-123456789"}}, format="json"
    )

    runtime_file = _credentials(node_client, weather).json()["runtime_file"]

    assert runtime_file["settings"] == {"units": "imperial", "note": "hello"}
    assert runtime_file["secret_settings"] == {"forecast_api_token": "token-123456789"}


def test_the_jwks_keeps_a_retired_key_for_24_hours(weather, node_client):
    first = PluginSigningKeyService().active_key().kid
    second = PluginSigningKeyService().rotate().kid

    kids_after_rotation = [key["kid"] for key in _credentials(node_client, weather).json()["runtime_file"]["jwks"]["keys"]]
    PluginSigningKey.objects.filter(kid=first).update(retired_at=timezone.now() - timedelta(hours=24, seconds=1))
    kids_a_day_later = [key["kid"] for key in _credentials(node_client, weather).json()["runtime_file"]["jwks"]["keys"]]

    assert kids_after_rotation == [second, first]
    assert kids_a_day_later == [second]


def test_a_rotation_changes_the_credentials_revision_but_not_the_settings_revision(weather, node_client):
    before = _desired_placement(node_client)

    PluginSigningKeyService().rotate()
    after = _desired_placement(node_client)

    assert after["credentials_revision"] != before["credentials_revision"]
    assert after["settings_revision"] == before["settings_revision"]
    assert after["restart_generation"] == before["restart_generation"]


def test_a_settings_change_changes_the_settings_revision_but_not_the_credentials_revision(weather, node_client, superadmin_client):
    before = _desired_placement(node_client)

    superadmin_client.patch(SETTINGS_URL, {"values": {"units": "imperial"}}, format="json")
    after = _desired_placement(node_client)

    assert after["settings_revision"] == before["settings_revision"] + 1
    assert after["credentials_revision"] == before["credentials_revision"]


def test_nothing_changes_the_revisions_when_nothing_changed(weather, node_client):
    assert _desired_placement(node_client) == _desired_placement(node_client)


def test_the_credentials_and_the_desired_state_agree_on_the_revisions(weather, node_client):
    desired = _desired_placement(node_client)

    credentials = _credentials(node_client, weather).json()

    assert credentials["credentials_revision"] == desired["credentials_revision"]
    assert credentials["settings_revision"] == desired["settings_revision"]


def test_another_node_s_placement_is_not_found(weather, other_node_client):
    response = other_node_client.post(_credentials_url(weather.placement.pk))

    assert response.status_code == 404
    assert response.json()["code"] == "placement_not_found"


def test_an_unknown_placement_is_not_found(plugin_node, node_client):
    response = node_client.post(_credentials_url(999999))

    assert response.status_code == 404
    assert response.json()["code"] == "placement_not_found"


SECRET_VALUE = "s3cret-forecast-token"


def test_a_credentials_validation_error_never_shows_a_secret():
    document = {
        "placement_id": 1,
        "credentials_revision": "a" * 64,
        "settings_revision": 0,
        "runtime_file": {"secret_settings": {"forecast_api_token": [SECRET_VALUE]}},
    }

    with pytest.raises(ValidationError) as raised:
        RuntimeCredentials.model_validate(document)

    assert SECRET_VALUE not in str(raised.value)
    assert SECRET_VALUE not in repr(raised.value)


def test_a_runtime_file_the_service_cannot_build_never_shows_a_secret(weather, plugin_node, monkeypatch):
    monkeypatch.setattr(
        "plugins.nodes.runtime_credentials_service.runtime_settings",
        lambda manifest, stored: ({}, {"forecast_api_token": [SECRET_VALUE]}),
    )

    with pytest.raises(ValidationError) as raised:
        RuntimeCredentialsService().credentials_for(plugin_node, weather.placement.pk)

    assert SECRET_VALUE not in str(raised.value)


# ---- service accounts ----

ME_URL = "/api/plugin-runtime/me/"


@pytest.fixture
def granted(weather, superadmin):
    """Factory → `organization` with a grant of Weather made through the grant service, in `state`."""

    mark_running(weather)

    def _make(organization, state=GrantState.ACTIVE):
        PluginGrantService().grant("weather", organization.pk, superadmin)
        PluginGrant.objects.filter(plugin=weather, org=organization).update(state=state)
        return organization

    return _make


def test_service_accounts_list_the_key_holding_grants_each_with_a_working_key(weather, node_client, granted, acme, beta):
    granted(acme)
    granted(beta, GrantState.GRANTING)
    granted(Organization.objects.create(name="failed-install"), GrantState.INSTALL_FAILED)
    granted(Organization.objects.create(name="suspended"), GrantState.SUSPENDED)

    runtime_file = RuntimeFile.model_validate(_credentials(node_client, weather).json()["runtime_file"])

    assert set(runtime_file.service_accounts) == {str(acme.pk), str(beta.pk)}
    assert runtime_file.service_accounts[str(acme.pk)].org_name == acme.name
    assert runtime_file.service_accounts[str(acme.pk)].grant_state == "active"
    assert runtime_file.service_accounts[str(beta.pk)].grant_state == "granting"
    for org_id, entry in runtime_file.service_accounts.items():
        response = service_account_client(entry.key).get(ME_URL)
        assert response.status_code == 200
        assert response.json()["organization"]["id"] == int(org_id)


def test_an_inactive_organization_gets_no_key(weather, node_client, granted, acme):
    granted(acme)
    Organization.objects.filter(pk=acme.pk).update(is_active=False)

    assert _credentials(node_client, weather).json()["runtime_file"]["service_accounts"] == {}


def test_every_fetch_mints_new_keys(weather, node_client, granted, acme):
    granted(acme)

    first = _credentials(node_client, weather).json()["runtime_file"]["service_accounts"][str(acme.pk)]["key"]
    second = _credentials(node_client, weather).json()["runtime_file"]["service_accounts"][str(acme.pk)]["key"]

    assert first != second


def test_the_revision_is_stable_across_fetches_and_never_follows_the_keys(weather, node_client, granted, acme):
    granted(acme)
    desired = _desired_placement(node_client)["credentials_revision"]

    first = _credentials(node_client, weather).json()["credentials_revision"]
    second = _credentials(node_client, weather).json()["credentials_revision"]

    assert first == second == desired == _desired_placement(node_client)["credentials_revision"]


def _revision_change(node_client, weather, change):
    before = _desired_placement(node_client)["credentials_revision"]
    change()
    after = _desired_placement(node_client)["credentials_revision"]
    assert after != before
    assert _credentials(node_client, weather).json()["credentials_revision"] == after


def test_a_new_grant_changes_the_revision(weather, node_client, granted, acme, beta):
    granted(beta)

    _revision_change(node_client, weather, lambda: granted(acme))


@pytest.mark.parametrize("state", [GrantState.ACTIVE, GrantState.INSTALL_FAILED])
def test_a_grant_changing_state_changes_the_revision(weather, node_client, granted, acme, state):
    granted(acme, GrantState.GRANTING)

    _revision_change(node_client, weather, lambda: PluginGrant.objects.filter(org=acme).update(state=state))


def test_renaming_a_granted_organization_changes_the_revision(weather, node_client, granted, acme):
    granted(acme)

    _revision_change(node_client, weather, lambda: Organization.objects.filter(pk=acme.pk).update(name="Acme renamed"))
