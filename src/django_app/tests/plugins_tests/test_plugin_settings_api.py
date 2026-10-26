"""SuperAdmin settings of a plugin's backend: secrets at rest, validation, restarts, blocking."""

import pytest
from plugins.models import PluginPlacement, PluginSettingValue
from rest_framework.test import APIClient
from tables.services.secrets import secret_encryption

from tests.plugins_tests.package_builder import TOKEN_SETTING, UNITS_SETTING

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

SETTINGS_URL = "/api/admin/plugins/weather/settings/"
RUNTIME_URL = "/api/admin/plugins/weather/runtime/"
SECRET = "forecast-token-1234"


def _setting(key, setting_type, **extra):
    return {"key": key, "type": setting_type, "label": key.title(), "description": f"The {key}.", "required": False, **extra}


EVERY_TYPE = [
    dict(UNITS_SETTING),
    dict(TOKEN_SETTING),
    _setting("title", "string"),
    _setting("notes", "text"),
    _setting("retries", "integer", default=3),
    _setting("verbose", "boolean"),
    _setting("endpoint", "url"),
    _setting("region", "string", required=True),
]


@pytest.fixture
def weather(backend_plugin):
    return backend_plugin(settings=EVERY_TYPE)


def _patch(client, **values):
    return client.patch(SETTINGS_URL, {"values": values}, format="json")


def _settings_revision(plugin):
    return PluginPlacement.objects.get(plugin=plugin).settings_revision


def _by_key(response):
    return {state["key"]: state for state in response.json()["settings"]}


def test_settings_are_listed_in_manifest_order_with_their_state(weather, superadmin_client):
    response = superadmin_client.get(SETTINGS_URL)

    assert response.status_code == 200
    body = response.json()
    assert [state["key"] for state in body["settings"]] == [setting["key"] for setting in EVERY_TYPE]
    assert body["missing_required"] == ["region"]
    assert _by_key(response)["units"] == {
        "key": "units",
        "type": "enum",
        "label": "Units",
        "description": "Units for every organization.",
        "required": True,
        "values": ["metric", "imperial"],
        "default": "metric",
        "value": None,
        "is_set": False,
        "tail": None,
        "updated_at": None,
        "updated_by": None,
    }


def test_a_secret_is_stored_encrypted_and_shown_only_by_its_tail(weather, superadmin_client, superadmin_user):
    response = _patch(superadmin_client, forecast_api_token=SECRET)

    assert response.status_code == 200
    shown = _by_key(response)["forecast_api_token"]
    assert (shown["value"], shown["default"], shown["is_set"], shown["tail"]) == (None, None, True, "1234")
    assert shown["updated_by"] == {"id": superadmin_user.id, "email": superadmin_user.email}
    stored = PluginSettingValue.objects.get(plugin=weather, key="forecast_api_token")
    assert stored.value is None
    assert SECRET not in stored.encrypted_value
    assert SECRET not in response.content.decode()


def test_a_short_secret_shows_no_tail(weather, superadmin_client):
    shown = _by_key(_patch(superadmin_client, forecast_api_token="short"))["forecast_api_token"]

    assert (shown["is_set"], shown["tail"]) == (True, None)


def test_plain_values_round_trip(weather, superadmin_client):
    _patch(superadmin_client, units="imperial", title="Forecast", retries=5, verbose=True, endpoint="https://api.example.com/v1")

    shown = _by_key(superadmin_client.get(SETTINGS_URL))

    assert {key: shown[key]["value"] for key in ("units", "title", "retries", "verbose", "endpoint")} == {
        "units": "imperial",
        "title": "Forecast",
        "retries": 5,
        "verbose": True,
        "endpoint": "https://api.example.com/v1",
    }


def test_only_the_named_keys_change(weather, superadmin_client):
    _patch(superadmin_client, title="Kept")

    _patch(superadmin_client, units="imperial")

    assert _by_key(superadmin_client.get(SETTINGS_URL))["title"]["value"] == "Kept"


def test_a_required_setting_with_a_default_may_be_cleared(weather, superadmin_client):
    _patch(superadmin_client, units="imperial")

    assert _patch(superadmin_client, units=None).status_code == 200


def test_null_clears_a_setting(weather, superadmin_client):
    _patch(superadmin_client, forecast_api_token=SECRET, title="Gone")

    response = _patch(superadmin_client, forecast_api_token=None, title=None)

    assert response.status_code == 200
    assert not PluginSettingValue.objects.filter(key__in=["forecast_api_token", "title"]).exists()


@pytest.mark.parametrize(
    ("values", "loc"),
    [
        ({"unknown": "x"}, "values.unknown"),
        ({"title": 5}, "values.title"),
        ({"title": "x" * 1001}, "values.title"),
        ({"notes": "x" * 10_001}, "values.notes"),
        ({"retries": True}, "values.retries"),
        ({"retries": 1.5}, "values.retries"),
        ({"retries": "3"}, "values.retries"),
        ({"retries": 2**53 + 1}, "values.retries"),
        ({"verbose": "yes"}, "values.verbose"),
        ({"endpoint": "ftp://example.com"}, "values.endpoint"),
        ({"endpoint": "not a url"}, "values.endpoint"),
        ({"endpoint": "https://example.com/" + "x" * 2000}, "values.endpoint"),
        ({"units": "kelvin"}, "values.units"),
        ({"forecast_api_token": ""}, "values.forecast_api_token"),
        ({"forecast_api_token": "x" * 4097}, "values.forecast_api_token"),
        ({"forecast_api_token": "\U0001f600" * 2049}, "values.forecast_api_token"),
        ({"region": None}, "values.region"),
    ],
)
def test_each_validation_rule(weather, superadmin_client, values, loc):
    response = superadmin_client.patch(SETTINGS_URL, {"values": values}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_plugin_settings"
    assert [error["loc"] for error in response.json()["errors"]] == [loc]
    assert not PluginSettingValue.objects.exists()


def test_values_at_the_limits_are_accepted(weather, superadmin_client):
    response = _patch(
        superadmin_client,
        title="x" * 1000,
        notes="x" * 10_000,
        retries=-(2**53),
        endpoint="http://example.com/" + "x" * 1981,
        forecast_api_token="x" * 4096,
        region="",
    )

    assert response.status_code == 200


def test_a_change_raises_the_settings_revision(weather, superadmin_client):
    _patch(superadmin_client, units="imperial")
    _patch(superadmin_client, forecast_api_token=SECRET)

    assert _settings_revision(weather) == 2


def test_writing_the_same_plain_value_again_does_not_restart(weather, superadmin_client):
    _patch(superadmin_client, units="imperial")

    _patch(superadmin_client, units="imperial")

    assert _settings_revision(weather) == 1


def test_writing_a_secret_always_restarts(weather, superadmin_client):
    _patch(superadmin_client, forecast_api_token=SECRET)

    _patch(superadmin_client, forecast_api_token=SECRET)

    assert _settings_revision(weather) == 2


def test_the_settings_api_never_decrypts_a_secret(weather, superadmin_client, mocker):
    _patch(superadmin_client, forecast_api_token=SECRET)
    decrypt = mocker.patch.object(secret_encryption, "decrypt")

    _patch(superadmin_client, forecast_api_token="another-token-5678", units="imperial")
    superadmin_client.get(SETTINGS_URL)

    decrypt.assert_not_called()


def test_changes_are_logged_by_key_without_values(weather, superadmin_client, mocker):
    info = mocker.patch("plugins.audit.logger.info")

    _patch(superadmin_client, forecast_api_token=SECRET, units="imperial")

    info.assert_called_once()
    assert info.call_args.kwargs["keys"] == "forecast_api_token,units"
    assert SECRET not in repr(info.call_args)


def test_a_missing_required_setting_blocks_the_process_until_it_is_set(weather, superadmin_client):
    blocked = superadmin_client.get(RUNTIME_URL).json()["placement"]

    _patch(superadmin_client, region="eu")
    unblocked = superadmin_client.get(RUNTIME_URL).json()["placement"]

    assert (blocked["desired_state"], blocked["blocked_reason"]) == ("stopped", "required_settings_missing")
    assert (unblocked["desired_state"], unblocked["blocked_reason"]) == ("running", None)
    assert superadmin_client.get(SETTINGS_URL).json()["missing_required"] == []


def test_a_plugin_without_a_backend_has_no_settings(running_plugin, superadmin_client):
    running_plugin()

    response = superadmin_client.get(SETTINGS_URL)

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_has_no_backend"


def test_an_unknown_plugin_is_not_found(superadmin_client):
    assert superadmin_client.get("/api/admin/plugins/nothing/settings/").json()["code"] == "plugin_not_found"


def test_an_org_admin_is_refused(weather, client_as, admin_acme):
    response = client_as(admin_acme).patch(SETTINGS_URL, {"values": {"units": "imperial"}}, format="json")

    assert response.status_code == 403
    assert not PluginSettingValue.objects.exists()


def test_an_api_key_is_refused(weather, issue_api_key, superadmin):
    raw_key, _ = issue_api_key(user=superadmin)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    assert client.get(SETTINGS_URL).status_code == 403
