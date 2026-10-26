"""Starting an upgrade: approving a newer package of an installed plugin."""

import pytest
from plugins.models import (
    ActivityAction,
    GrantState,
    Plugin,
    PluginActivityEvent,
    PluginDatabase,
    PluginGrant,
    PluginPackage,
    PluginPlacement,
    PluginServiceAccount,
    PluginSettingValue,
    PluginState,
    PluginUpgrade,
    ReviewState,
    UpgradeStage,
)
from plugins.packages.spa_publisher import CURRENT_LINK

from tests.plugins_tests.package_builder import GEOCODING_HOST, sample_files, sample_manifest
from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    FORECAST_HOST,
    active_grant,
    newer,
    upgrade_of,
    upload,
    weather,
    weather_manifest,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"
REGION = {"key": "region", "type": "string", "label": "Region", "description": "Where.", "required": True}


def _approve(client, package, **body):
    body.setdefault("untrusted_acknowledged", True)
    return client.post(f"{PACKAGES_URL}{package.pk}/approve/", body, format="json")


def _baseline(plugin) -> int:
    return Plugin.objects.get(pk=plugin.pk).current_package_id


def _nothing_started(weather, package):
    package.refresh_from_db()
    plugin = Plugin.objects.get(pk=weather.pk)
    return (
        package.review_state == ReviewState.PENDING
        and not PluginUpgrade.objects.filter(plugin=weather).exists()
        and plugin.state == PluginState.RUNNING
        and plugin.current_package_id == weather.current_package_id
    )


def test_new_access_without_the_acknowledgement_is_refused_and_nothing_changes(weather, newer, superadmin_client, spa_root):
    package = newer(outbound_hosts=[GEOCODING_HOST, FORECAST_HOST])

    response = _approve(superadmin_client, package, reviewed_against_package_id=_baseline(weather))

    assert (response.status_code, response.json()["code"]) == (400, "access_growth_not_acknowledged")
    assert _nothing_started(weather, package)
    assert not (spa_root / "weather" / "0.7.0").exists()


def test_with_the_acknowledgement_the_upgrade_starts_while_the_plugin_keeps_running(
    weather, newer, superadmin_client, spa_root, django_capture_on_commit_callbacks
):
    package = newer(outbound_hosts=[GEOCODING_HOST, FORECAST_HOST])

    with django_capture_on_commit_callbacks(execute=True):
        response = _approve(
            superadmin_client,
            package,
            reviewed_against_package_id=_baseline(weather),
            access_growth_acknowledged=True,
        )

    assert response.status_code == 202, response.content
    body = response.json()
    assert (body["state"], body["current_version"]) == ("running", "0.6.0")
    assert body["open_upgrade"]["stage"] == "preparing"
    assert body["open_upgrade"]["from_version"] == "0.6.0"
    assert body["upgrade"] == {"to_version": "0.7.0", "stage": "preparing", "failed": False}
    package.refresh_from_db()
    assert package.review_state == ReviewState.APPROVED
    assert (spa_root / "weather" / "0.7.0").is_dir()
    assert (spa_root / "weather" / CURRENT_LINK).readlink().name == "0.6.0"
    upgrade = PluginUpgrade.objects.get(plugin=weather)
    assert (upgrade.access_growth_acknowledged, upgrade.backup_required, upgrade.adds_backend) == (True, True, False)


@pytest.mark.parametrize("reviewed", [None, "current_plus_one"])
def test_an_approval_that_does_not_name_the_reviewed_baseline_is_outdated(weather, newer, superadmin_client, reviewed):
    package = newer()
    body = {} if reviewed is None else {"reviewed_against_package_id": package.pk}

    response = _approve(superadmin_client, package, access_growth_acknowledged=True, **body)

    assert (response.status_code, response.json()["code"]) == (409, "review_outdated")
    assert _nothing_started(weather, package)


def test_the_untrusted_acknowledgement_is_still_needed_and_checked_after_the_conflicts(weather, newer, superadmin_client):
    package = newer()

    outdated = _approve(superadmin_client, package, untrusted_acknowledged=False)
    unacknowledged = _approve(
        superadmin_client, package, untrusted_acknowledged=False, reviewed_against_package_id=_baseline(weather)
    )

    assert (outdated.status_code, outdated.json()["code"]) == (409, "review_outdated")
    assert (unacknowledged.status_code, unacknowledged.json()["code"]) == (400, "untrusted_not_acknowledged")
    assert _nothing_started(weather, package)


def test_a_setting_the_new_version_needs_must_be_given(weather, newer, superadmin_client):
    package = newer(settings=[REGION])

    response = _approve(superadmin_client, package, reviewed_against_package_id=_baseline(weather))

    assert (response.status_code, response.json()["code"]) == (400, "invalid_plugin_settings")
    assert response.json()["errors"] == [
        {"loc": "settings.region", "message": "is required by the new version and has no value"}
    ]
    assert _nothing_started(weather, package)


def test_settings_given_with_the_approval_are_saved_without_a_restart(weather, newer, superadmin_client):
    token = {"key": "token", "type": "secret", "label": "Token", "description": "Secret.", "required": True}
    package = newer(settings=[REGION, token])
    generation = PluginPlacement.objects.get(plugin=weather).settings_revision

    response = _approve(
        superadmin_client,
        package,
        reviewed_against_package_id=_baseline(weather),
        settings={"region": "eu-west", "token": "s3cret-value"},
    )

    assert response.status_code == 202, response.content
    stored = {row.key: row for row in PluginSettingValue.objects.filter(plugin=weather)}
    assert stored["region"].value == "eu-west"
    assert stored["token"].value is None and stored["token"].encrypted_value not in (None, "s3cret-value")
    assert PluginPlacement.objects.get(plugin=weather).settings_revision == generation


def test_a_setting_unknown_to_the_new_version_is_refused_at_its_location(weather, newer, superadmin_client):
    response = _approve(
        superadmin_client, newer(), reviewed_against_package_id=_baseline(weather), settings={"colour": "blue"}
    )

    assert response.json()["errors"] == [{"loc": "settings.colour", "message": "is not a setting of this plugin"}]


def test_a_frontend_only_upgrade_completes_at_once(
    running_plugin, installation, superadmin, superadmin_client, spa_root, acme, django_capture_on_commit_callbacks
):
    plugin = running_plugin(version="0.6.0")
    grant = active_grant(plugin, acme, superadmin)
    previous = plugin.current_package_id
    package = upload(installation, superadmin, sample_manifest(version="0.7.0", name="Weather Lite"))

    with django_capture_on_commit_callbacks(execute=True):
        response = _approve(superadmin_client, package, reviewed_against_package_id=previous)

    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["state"], body["current_version"], body["name"], body["open_upgrade"]) == (
        "running",
        "0.7.0",
        "Weather Lite",
        None,
    )
    assert body["last_upgrade"]["stage"] == "done"
    assert (spa_root / "weather" / CURRENT_LINK).readlink().name == "0.7.0"
    assert not (spa_root / "weather" / "0.6.0").exists()
    assert not PluginPackage.objects.filter(pk=previous).exists()
    grant.refresh_from_db()
    assert (grant.state, grant.installed_version) == (GrantState.ACTIVE, "0.7.0")
    actions = list(PluginActivityEvent.objects.filter(plugin_identifier="weather").values_list("action", flat=True))
    assert ActivityAction.PLUGIN_UPGRADE_STARTED in actions and ActivityAction.PLUGIN_UPGRADED in actions


def test_a_version_that_adds_a_backend_gets_a_placement_accounts_and_a_database_and_starts_migrating(
    running_plugin, installation, superadmin, superadmin_client, plugin_node, plugin_database_server, acme, beta
):
    plugin = running_plugin(version="0.6.0")
    active_grant_without_account = PluginGrant.objects.create(
        plugin=plugin, org=acme, state=GrantState.ACTIVE, installed_version="0.6.0", created_by=superadmin
    )
    PluginGrant.objects.create(plugin=plugin, org=beta, state=GrantState.PURGING, created_by=superadmin)
    manifest = weather_manifest("0.7.0")
    package = upload(installation, superadmin, manifest, sample_files(manifest))

    response = _approve(
        superadmin_client,
        package,
        reviewed_against_package_id=plugin.current_package_id,
        access_growth_acknowledged=True,
    )

    assert response.status_code == 202, response.content
    upgrade = PluginUpgrade.objects.get(plugin=plugin)
    assert (upgrade.stage, upgrade.adds_backend, upgrade.backup_required) == (UpgradeStage.MIGRATING, True, False)
    assert upgrade.migrations_started_at is not None
    assert PluginPlacement.objects.filter(plugin=plugin).exists()
    assert PluginDatabase.objects.filter(plugin=plugin).exists()
    assert list(PluginServiceAccount.objects.filter(grant__plugin=plugin).values_list("grant_id", flat=True)) == [
        active_grant_without_account.pk
    ]
    assert Plugin.objects.get(pk=plugin.pk).state == PluginState.RUNNING


def test_a_version_that_adds_a_database_gets_its_record_at_approval(backend_plugin, installation, superadmin, superadmin_client, plugin_database_server):
    from tests.plugins_tests.conftest import mark_running

    plugin = mark_running(backend_plugin(version="0.6.0"))
    manifest = weather_manifest("0.7.0")

    response = _approve(
        superadmin_client,
        upload(installation, superadmin, manifest, sample_files(manifest)),
        reviewed_against_package_id=plugin.current_package_id,
        access_growth_acknowledged=True,
    )

    assert response.status_code == 202, response.content
    assert PluginDatabase.objects.filter(plugin=plugin).exists()
    assert PluginUpgrade.objects.get(plugin=plugin).backup_required is False


def test_an_upgrade_cannot_start_while_the_plugin_is_provisioning(weather, newer, superadmin_client):
    package = newer()
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.PROVISIONING)

    response = _approve(superadmin_client, package, reviewed_against_package_id=_baseline(weather))

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_upgradable")


def test_an_upgrade_cannot_start_while_another_one_works(weather, newer, upgrade_of, superadmin_client):
    upgrade = upgrade_of(newer("0.7.0"))
    package = newer("0.8.0")

    response = _approve(superadmin_client, package, reviewed_against_package_id=upgrade.to_package_id)

    assert (response.status_code, response.json()["code"]) == (409, "plugin_not_upgradable")


def test_an_uninstalled_plugin_is_refused_before_the_upgrade_rules(weather, newer, superadmin_client):
    package = newer()
    Plugin.objects.filter(pk=weather.pk).update(state=PluginState.UNINSTALLING)

    response = _approve(superadmin_client, package, reviewed_against_package_id=_baseline(weather))

    assert (response.status_code, response.json()["code"]) == (409, "plugin_uninstalling")


def test_starting_records_the_activity_and_the_log(weather, newer, upgrade_of, log_messages):
    upgrade_of(newer())

    event = PluginActivityEvent.objects.get(action=ActivityAction.PLUGIN_UPGRADE_STARTED)
    assert event.detail == {
        "from_version": "0.6.0",
        "to_version": "0.7.0",
        "access_growth_acknowledged": True,
        "untrusted_acknowledged": True,
        "replaced_version": None,
    }
    assert any(message.startswith("plugins.upgrade.started ") and "to=0.7.0" in message for message in log_messages)
