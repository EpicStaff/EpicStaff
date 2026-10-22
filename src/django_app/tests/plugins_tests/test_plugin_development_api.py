"""A SuperAdmin's control of plugin development mode for one plugin: its target and its keys."""

import json

import pytest
from epicstaff_plugin.contracts.runtime import RuntimeFile
from plugins.identity.service_account_keys import ServiceAccountKeyService
from plugins.lifecycle.suspension_service import PluginSuspensionService
from plugins.models import (
    ActivityAction,
    Plugin,
    PluginActivityEvent,
    PluginDevelopmentTarget,
    PluginServiceAccountKey,
    ServiceAccountKeyPurpose,
)

from tests.plugins_tests.conftest import (
    DEVELOPMENT_API_PORT,
    DEVELOPMENT_HOST_ADDRESS,
    mark_running,
    service_account_client,
    upload_file,
)
from tests.plugins_tests.package_builder import backend_manifest, build_package, sample_files

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root", "development_host_resolves"),
]

ME_URL = "/api/plugin-runtime/me/"


def _url(identifier="weather"):
    return f"/api/admin/plugins/{identifier}/development/"


@pytest.fixture
def weather(backend_plugin):
    """Weather with a backend and a page, running."""
    return mark_running(backend_plugin())


@pytest.fixture
def backend_only(installation, superadmin, plugin_node, django_capture_on_commit_callbacks):
    """A plugin with a backend and no page, running."""
    manifest = backend_manifest(id="worker")
    del manifest["spa"]
    files = {path: data for path, data in sample_files(manifest).items() if not path.startswith("spa/")}
    data = build_package(files, manifest=manifest)
    package = installation.upload(upload_file(data), len(data), superadmin)
    with django_capture_on_commit_callbacks(execute=True):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=True)
    return mark_running(Plugin.objects.get(pk=package.plugin_id))


@pytest.fixture
def page_only(running_plugin):
    return running_plugin()


def _errors(response):
    return [error["loc"] for error in response.json()["errors"]]


@pytest.mark.usefixtures("development_mode")
def test_the_tab_of_a_plugin_with_a_backend_and_a_page_and_no_target(weather, superadmin_client):
    response = superadmin_client.get(_url())

    assert response.status_code == 200
    assert response.json() == {
        "development_mode": True,
        "host": "host.docker.internal",
        "host_address": DEVELOPMENT_HOST_ADDRESS,
        "api_url": f"http://127.0.0.1:{DEVELOPMENT_API_PORT}/api/",
        "can_use_backend": True,
        "can_use_spa": True,
        "target": None,
        "runtime_file_issued_at": None,
    }


def test_with_the_mode_off_the_stored_target_shows_but_nothing_is_resolved(
    weather, superadmin_client, development_host_resolves
):
    PluginDevelopmentTarget.objects.create(plugin=weather, backend_port=8001)

    body = superadmin_client.get(_url()).json()

    assert (body["development_mode"], body["host_address"], body["api_url"]) == (False, None, None)
    assert (body["target"]["backend_port"], body["target"]["spa_port"]) == (8001, None)
    assert development_host_resolves.calls == []


@pytest.mark.usefixtures("development_mode")
def test_an_unresolved_host_has_no_address(weather, superadmin_client, development_host_unresolved):
    assert superadmin_client.get(_url()).json()["host_address"] is None


@pytest.mark.usefixtures("development_mode")
def test_only_the_parts_the_package_has_can_be_used(backend_only, page_only, superadmin_client):
    backend = superadmin_client.get(_url(backend_only.identifier)).json()
    page = superadmin_client.get(_url(page_only.identifier)).json()

    assert (backend["can_use_backend"], backend["can_use_spa"]) == (True, False)
    assert (page["can_use_backend"], page["can_use_spa"]) == (False, True)


@pytest.mark.parametrize("method", ["get", "put", "delete"])
@pytest.mark.usefixtures("development_mode")
def test_an_unknown_plugin_is_not_found(superadmin_client, method):
    response = getattr(superadmin_client, method)(_url("nope"), {"backend_port": 8001}, format="json")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


@pytest.mark.usefixtures("development_mode")
def test_setting_ports_stores_them_and_records_the_change(
    weather, superadmin_client, superadmin_user, log_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_client.put(_url(), {"backend_port": 8001, "spa_port": 5173}, format="json")

    assert response.status_code == 200
    target = response.json()["target"]
    assert (target["backend_port"], target["spa_port"]) == (8001, 5173)
    assert target["updated_by"] == {"id": superadmin_user.pk, "email": superadmin_user.email}
    stored = PluginDevelopmentTarget.objects.get(plugin=weather)
    assert (stored.backend_port, stored.spa_port, stored.updated_by_id) == (8001, 5173, superadmin_user.pk)
    event = PluginActivityEvent.objects.get(action=ActivityAction.DEVELOPMENT_TARGET_SET)
    assert (event.plugin_identifier, event.organization_id, event.actor_kind) == ("weather", None, "superadmin")
    assert event.detail == {"backend_port": 8001, "spa_port": 5173}
    assert any(
        line.startswith("plugins.development.target_set ") and "backend_port=8001 spa_port=5173" in line
        for line in log_messages
    )


@pytest.mark.usefixtures("development_mode")
def test_setting_the_same_ports_again_records_nothing_new(weather, superadmin_client):
    for _ in range(2):
        assert superadmin_client.put(_url(), {"backend_port": 8001}, format="json").status_code == 200
    superadmin_client.put(_url(), {"backend_port": 8002}, format="json")

    details = list(
        PluginActivityEvent.objects.filter(action=ActivityAction.DEVELOPMENT_TARGET_SET)
        .order_by("pk")
        .values_list("detail", flat=True)
    )
    assert details == [{"backend_port": 8001, "spa_port": None}, {"backend_port": 8002, "spa_port": None}]


@pytest.mark.usefixtures("development_mode")
def test_one_server_may_serve_both(weather, superadmin_client):
    response = superadmin_client.put(_url(), {"backend_port": 8001, "spa_port": 8001}, format="json")

    assert response.status_code == 200


@pytest.mark.usefixtures("development_mode")
def test_setting_ports_issues_no_key(weather, superadmin_client, service_account_key, acme):
    service_account_key(weather, acme)

    superadmin_client.put(_url(), {"backend_port": 8001}, format="json")

    assert not PluginServiceAccountKey.objects.filter(purpose=ServiceAccountKeyPurpose.DEVELOPMENT).exists()


def test_ports_cannot_be_set_while_the_mode_is_off(weather, superadmin_client):
    response = superadmin_client.put(_url(), {"backend_port": 8001}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_development_mode_off"
    assert not PluginDevelopmentTarget.objects.exists()


@pytest.mark.usefixtures("development_mode")
def test_ports_cannot_be_set_for_a_plugin_that_is_not_running(backend_plugin, superadmin_client):
    backend_plugin()

    response = superadmin_client.put(_url(), {"backend_port": 8001}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_not_running"


@pytest.mark.usefixtures("development_mode")
def test_the_mode_is_refused_before_the_body_is_read(backend_plugin, superadmin_client, settings):
    settings.PLUGINS_DEV_MODE = False
    backend_plugin()

    response = superadmin_client.put(_url(), {"backend_port": "nonsense"}, format="json")

    assert response.json()["code"] == "plugin_development_mode_off"


@pytest.mark.parametrize(
    ("plugin_fixture", "body", "loc"),
    [
        ("page_only", {"backend_port": 8001}, "backend_port"),
        ("backend_only", {"spa_port": 5173}, "spa_port"),
        ("weather", {"backend_port": None, "spa_port": None}, "non_field_errors"),
        ("weather", {}, "non_field_errors"),
        ("weather", {"backend_port": 1023}, "backend_port"),
        ("weather", {"spa_port": 65536}, "spa_port"),
        ("weather", {"backend_port": "eight"}, "backend_port"),
        ("weather", {"backend_port": DEVELOPMENT_API_PORT}, "backend_port"),
        ("weather", {"spa_port": DEVELOPMENT_API_PORT}, "spa_port"),
    ],
)
@pytest.mark.usefixtures("development_mode")
def test_invalid_ports_are_refused_with_their_location(request, superadmin_client, plugin_fixture, body, loc):
    plugin = request.getfixturevalue(plugin_fixture)

    response = superadmin_client.put(_url(plugin.identifier), body, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"
    assert _errors(response) == [loc]
    assert not PluginDevelopmentTarget.objects.exists()


@pytest.mark.usefixtures("development_mode")
def test_stopping_development_deletes_the_target_and_revokes_only_development_keys(
    weather, superadmin_client, service_account_key, acme, log_messages, django_capture_on_commit_callbacks
):
    node_key = service_account_key(weather, acme)
    development_key = _development_key(weather, acme)
    superadmin_client.put(_url(), {"backend_port": 8001}, format="json")

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_client.delete(_url())

    assert response.status_code == 204
    assert not PluginDevelopmentTarget.objects.exists()
    assert service_account_client(node_key, acme).get(ME_URL).status_code == 200
    development = service_account_client(development_key, acme, development_listener="1")
    assert development.get(ME_URL).status_code == 401
    event = PluginActivityEvent.objects.get(action=ActivityAction.DEVELOPMENT_TARGET_CLEARED)
    assert (event.organization_id, event.detail) == (None, {"revoked_keys": 1})
    assert any(line.startswith("plugins.development.target_cleared ") and "revoked_keys=1" in line for line in log_messages)
    assert superadmin_client.get(_url()).json()["runtime_file_issued_at"] is None


@pytest.mark.usefixtures("development_mode")
def test_stopping_twice_answers_204_and_records_once(weather, superadmin_client):
    superadmin_client.put(_url(), {"backend_port": 8001}, format="json")

    assert superadmin_client.delete(_url()).status_code == 204
    assert superadmin_client.delete(_url()).status_code == 204
    assert PluginActivityEvent.objects.filter(action=ActivityAction.DEVELOPMENT_TARGET_CLEARED).count() == 1


def test_development_can_be_stopped_while_the_mode_is_off(weather, superadmin_client, service_account_key, acme):
    service_account_key(weather, acme)
    development_key = _development_key(weather, acme)
    PluginDevelopmentTarget.objects.create(plugin=weather, backend_port=8001)

    assert superadmin_client.delete(_url()).status_code == 204

    assert not PluginDevelopmentTarget.objects.exists()
    assert PluginServiceAccountKey.objects.get(key_hash=_hash(development_key)).revoked_at is not None


def test_deleting_the_plugin_deletes_its_target(weather):
    PluginDevelopmentTarget.objects.create(plugin=weather, spa_port=5173)

    Plugin.objects.filter(pk=weather.pk).delete()

    assert not PluginDevelopmentTarget.objects.exists()


# ---- the development runtime file ----

SECRET_TOKEN = "forecast-token-that-never-appears-anywhere-else"


def _runtime_file_url(identifier="weather"):
    return f"{_url(identifier)}runtime-file/"


def _download(client, identifier="weather"):
    return client.post(_runtime_file_url(identifier))


@pytest.fixture
def granted_weather(weather, service_account_key, acme, superadmin_client):
    """Weather running in Acme, with its node key minted and a secret setting stored."""
    service_account_key(weather, acme)
    response = superadmin_client.patch(
        "/api/admin/plugins/weather/settings/", {"values": {"forecast_api_token": SECRET_TOKEN}}, format="json"
    )
    assert response.status_code == 200
    return weather


def test_the_runtime_file_needs_development_mode(granted_weather, superadmin_client):
    response = _download(superadmin_client)

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_development_mode_off"
    assert not PluginServiceAccountKey.objects.filter(purpose=ServiceAccountKeyPurpose.DEVELOPMENT).exists()


@pytest.mark.usefixtures("development_mode")
def test_a_plugin_without_a_backend_has_no_runtime_file(page_only, superadmin_client):
    response = _download(superadmin_client, page_only.identifier)

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_has_no_backend"


@pytest.mark.usefixtures("development_mode")
def test_a_plugin_that_is_not_running_has_no_runtime_file(backend_plugin, superadmin_client):
    backend_plugin()

    response = _download(superadmin_client)

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_not_running"


@pytest.mark.usefixtures("development_mode")
def test_an_unknown_plugin_has_no_runtime_file(superadmin_client):
    response = _download(superadmin_client, "nope")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


@pytest.mark.usefixtures("development_mode")
def test_the_runtime_file_is_an_attachment_no_cache_keeps(granted_weather, superadmin_client):
    response = _download(superadmin_client)

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response["Content-Disposition"] == 'attachment; filename="weather-development-runtime.json"'


@pytest.mark.usefixtures("development_mode")
def test_the_runtime_file_is_the_node_s_except_its_keys_and_api_address(
    granted_weather, superadmin_client, node_client, settings, acme
):
    settings.PLUGINS_DEV_API_PORT = "9100"

    development = _download(superadmin_client).json()
    node = node_client.post(
        f"/api/plugin-nodes/self/placements/{granted_weather.placement.pk}/runtime-credentials/"
    ).json()["runtime_file"]

    parsed = RuntimeFile.model_validate_json(json.dumps(development), extra="ignore")
    assert parsed.epicstaff_api_url == "http://127.0.0.1:9100/api/"
    assert parsed.secret_settings == {"forecast_api_token": SECRET_TOKEN}
    differing = {"service_accounts", "epicstaff_api_url"}
    assert {key: value for key, value in development.items() if key not in differing} == {
        key: value for key, value in node.items() if key not in differing
    }
    org = str(acme.pk)
    assert development["service_accounts"][org]["key"] != node["service_accounts"][org]["key"]
    assert {key: value for key, value in development["service_accounts"][org].items() if key != "key"} == {
        key: value for key, value in node["service_accounts"][org].items() if key != "key"
    }


@pytest.mark.usefixtures("development_mode")
def test_the_runtime_file_holds_keys_only_for_this_plugin_s_key_holding_grants(
    granted_weather, backend_plugin, service_account_key, superadmin_client, superadmin, acme, beta
):
    radar = mark_running(backend_plugin(id="radar"))
    service_account_key(radar, acme)
    service_account_key(granted_weather, beta)
    PluginSuspensionService().suspend("weather", granted_weather.grants.get(org=beta).pk, superadmin)

    accounts = _download(superadmin_client).json()["service_accounts"]

    assert list(accounts) == [str(acme.pk)]
    development = service_account_client(accounts[str(acme.pk)]["key"], acme, development_listener="1")
    assert development.get(ME_URL).json()["plugin"]["identifier"] == "weather"
    assert PluginServiceAccountKey.objects.filter(purpose=ServiceAccountKeyPurpose.DEVELOPMENT).count() == 1
    assert not PluginServiceAccountKey.objects.filter(
        purpose=ServiceAccountKeyPurpose.DEVELOPMENT, service_account__grant__plugin=radar
    ).exists()


@pytest.mark.usefixtures("development_mode")
def test_downloading_again_stops_the_previous_file_s_keys(granted_weather, superadmin_client, acme):
    first = _download(superadmin_client).json()["service_accounts"][str(acme.pk)]["key"]
    second = _download(superadmin_client).json()["service_accounts"][str(acme.pk)]["key"]

    assert service_account_client(first, acme, development_listener="1").get(ME_URL).status_code == 401
    assert service_account_client(second, acme, development_listener="1").get(ME_URL).status_code == 200


@pytest.mark.usefixtures("development_mode")
def test_a_download_is_recorded_without_the_file(
    granted_weather, superadmin_client, superadmin_user, log_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        body = _download(superadmin_client).json()

    key = next(iter(body["service_accounts"].values()))["key"]
    event = PluginActivityEvent.objects.get(action=ActivityAction.DEVELOPMENT_RUNTIME_FILE_ISSUED)
    assert (event.organization_id, event.actor_user_id, event.detail) == (None, superadmin_user.pk, {"organizations": 1})
    assert [line for line in log_messages if line.startswith("plugins.development.runtime_file_issued")] == [
        f"plugins.development.runtime_file_issued actor={superadmin_user.email} (id {superadmin_user.pk}) "
        "plugin=weather organizations=1"
    ]
    for secret in (key, SECRET_TOKEN, key[12:]):
        assert not any(secret in line for line in log_messages)
        assert secret not in json.dumps(list(PluginActivityEvent.objects.values_list("detail", flat=True)))
    assert superadmin_client.get(_url()).json()["runtime_file_issued_at"] is not None


@pytest.mark.usefixtures("development_mode")
def test_a_runtime_file_that_cannot_be_built_mints_nothing(granted_weather, superadmin_client, acme, monkeypatch):
    earlier = _download(superadmin_client).json()["service_accounts"][str(acme.pk)]["key"]

    def refuse(document):
        raise ValueError("the document does not validate")

    monkeypatch.setattr("plugins.development.development_runtime.RuntimeFile.model_validate", refuse)

    with pytest.raises(ValueError):
        _download(superadmin_client)

    assert service_account_client(earlier, acme, development_listener="1").get(ME_URL).status_code == 200
    assert PluginServiceAccountKey.objects.filter(purpose=ServiceAccountKeyPurpose.DEVELOPMENT).count() == 1


def _development_key(plugin, organization) -> str:
    minted = ServiceAccountKeyService().mint_development_keys(plugin)
    return next(key.raw_key for key in minted if key.service_account.grant.org_id == organization.pk)


def _hash(raw_key: str) -> str:
    from plugins.identity.service_account_keys import hash_service_account_key

    return hash_service_account_key(raw_key)
