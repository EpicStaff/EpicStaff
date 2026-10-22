"""The review of a new version: the access it needs approved, and everything else it changes."""

import pytest
from plugins.models import PluginDatabase, PluginPackage, PluginSettingValue, PluginUpgrade, Trust
from plugins.packages.upgrade_review import access_growth
from epicstaff_plugin.contracts.manifest import PluginManifest

from tests.plugins_tests.conftest import WEATHER_ACCESS
from tests.plugins_tests.package_builder import PING_PATH, TOKEN_SETTING, UNITS_SETTING, sample_files
from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    DATABASE_SIZE,
    FORECAST_HOST,
    SECOND_MIGRATION,
    SECOND_MIGRATION_SQL,
    active_grant,
    newer,
    upgrade_of,
    weather,
    weather_manifest,
)
from tests.plugins_tests.package_builder import GEOCODING_HOST, sample_manifest
from tests.plugins_tests.upgrade_fixtures import upload

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"


def _review(client, package):
    response = client.get(f"{PACKAGES_URL}{package.pk}/review/")
    assert response.status_code == 200, response.content
    return response.json()


def _manifest(**changes) -> PluginManifest:
    return PluginManifest.model_validate(weather_manifest("0.7.0", **changes))


BASE = _manifest()


def _path(**changes) -> dict:
    return {**PING_PATH, **changes}


# ---- access growth, one case per rule ----


def test_a_new_resource_type_is_growth():
    growth = access_growth(_manifest(access=WEATHER_ACCESS[:1]), _manifest(access=WEATHER_ACCESS[:2]))

    assert growth.requires_acknowledgement
    assert growth.access == [
        {
            "resource_type": "files",
            "resource_label": growth.access[0]["resource_label"],
            "actions": ["read", "create"],
            "reason": "Stores the readme.",
        }
    ]


def test_a_new_action_on_a_declared_type_is_growth_with_only_the_new_action():
    before = [{**WEATHER_ACCESS[0], "actions": ["read", "create"]}]

    growth = access_growth(_manifest(access=before), _manifest(access=WEATHER_ACCESS[:1]))

    assert [(row["resource_type"], row["actions"]) for row in growth.access] == [("flows", ["update", "use"])]


def test_a_new_outbound_host_is_growth():
    growth = access_growth(BASE, _manifest(outbound_hosts=[GEOCODING_HOST, FORECAST_HOST]))

    assert growth.outbound_hosts == [FORECAST_HOST]


def test_a_new_wildcard_is_growth_even_when_it_covers_a_listed_host():
    wildcard = {"host": "*.open-meteo.com", "reason": "Every Open-Meteo service."}

    growth = access_growth(BASE, _manifest(outbound_hosts=[GEOCODING_HOST, wildcard]))

    assert growth.outbound_hosts == [wildcard]


def test_a_new_public_path_is_growth():
    status = _path(path="/api/status")

    growth = access_growth(BASE, _manifest(public_paths=[PING_PATH, status]))

    assert growth.public_paths == [{**status, "change": "new"}]


@pytest.mark.parametrize(
    "widened",
    [
        {"match": "prefix"},
        {"methods": ["GET", "POST"]},
        {"rate_limit_per_minute": PING_PATH["rate_limit_per_minute"] + 1},
        {"max_body_kb": PING_PATH["max_body_kb"] + 1},
    ],
)
def test_every_way_of_widening_a_public_path_is_growth(widened):
    growth = access_growth(BASE, _manifest(public_paths=[_path(**widened)]))

    assert [row["change"] for row in growth.public_paths] == ["widened"]


def test_narrowing_is_no_growth():
    wide = _manifest(
        access=WEATHER_ACCESS,
        public_paths=[_path(methods=["GET", "POST"], rate_limit_per_minute=600, max_body_kb=64)],
    )
    narrow = _manifest(access=WEATHER_ACCESS[:1], public_paths=[PING_PATH], outbound_hosts=[])

    growth = access_growth(wide, narrow)

    assert not growth.requires_acknowledgement
    assert (growth.access, growth.outbound_hosts, growth.public_paths) == ([], [], [])


# ---- the review endpoint ----


def test_a_first_install_has_no_upgrade_review(installation, superadmin, superadmin_client):
    package = upload(installation, superadmin, weather_manifest("0.6.0"))

    review = _review(superadmin_client, package)

    assert (review["is_upgrade"], review["current_version"]) == (False, None)
    assert (review["access_growth"], review["upgrade"]) == (None, None)


def test_the_review_of_a_new_version_names_its_baseline_and_what_it_adds(weather, newer, superadmin_client, superadmin, acme, beta):
    active_grant(weather, acme, superadmin)
    active_grant(weather, beta, superadmin)
    package = newer("0.7.0", outbound_hosts=[GEOCODING_HOST, FORECAST_HOST], hooks={"upgrade": True})

    review = _review(superadmin_client, package)

    assert (review["is_upgrade"], review["current_version"]) == (True, "0.6.0")
    assert review["access_growth"]["requires_acknowledgement"] is True
    assert review["access_growth"]["outbound_hosts"] == [FORECAST_HOST]
    upgrade = review["upgrade"]
    assert upgrade["baseline_package_id"] == weather.current_package_id
    assert (upgrade["from_version"], upgrade["replaces_version"]) == ("0.6.0", None)
    assert (upgrade["maintenance"], upgrade["backend"], upgrade["database"]) == (True, "unchanged", "unchanged")
    assert upgrade["migrations_added"] == ["002_conditions.sql"]
    assert (upgrade["hooks_added"], upgrade["hooks_removed"], upgrade["has_upgrade_hook"]) == (["upgrade"], [], True)
    assert upgrade["backup"] == {
        "required": True,
        "database_size_bytes": DATABASE_SIZE,
        "database_name": "plugin_weather",
    }
    assert upgrade["organizations_going_offline"] == 2
    assert upgrade["cancellable"] is True


def test_migrations_are_compared_with_the_ledger_once_the_database_reported(weather, newer, superadmin_client):
    record = PluginDatabase.objects.get(plugin=weather)
    record.ledger = [*record.ledger, {"name": "002_conditions.sql", "sha256": PluginPackage.objects.get(pk=newer().pk).migration_files[1]["sha256"]}]
    record.save(update_fields=["ledger"])
    package = PluginPackage.objects.get(plugin=weather, review_state="pending")

    assert _review(superadmin_client, package)["upgrade"]["migrations_added"] == []


def test_without_a_report_migrations_are_compared_with_the_baseline(weather, newer, superadmin_client):
    PluginDatabase.objects.filter(plugin=weather).update(ready_at=None, ledger=[])

    upgrade = _review(superadmin_client, newer())["upgrade"]

    assert upgrade["migrations_added"] == ["002_conditions.sql"]
    assert upgrade["backup"]["required"] is False


@pytest.mark.parametrize(
    ("baseline_trust", "new_trust", "same_signer", "expected"),
    [
        (Trust.UNTRUSTED, Trust.UNTRUSTED, True, "none"),
        (Trust.TRUSTED, Trust.UNTRUSTED, True, "became_untrusted"),
        (Trust.UNTRUSTED, Trust.TRUSTED, True, "became_trusted"),
        (Trust.TRUSTED, Trust.TRUSTED, False, "signer_changed"),
        (Trust.TRUSTED, Trust.TRUSTED, True, "none"),
    ],
)
def test_the_trust_change_is_shown(weather, newer, superadmin_client, baseline_trust, new_trust, same_signer, expected):
    key = "RWQ" + "a" * 53
    package = newer()
    PluginPackage.objects.filter(pk=weather.current_package_id).update(
        trust=baseline_trust, signer_public_key=key if baseline_trust == Trust.TRUSTED else None
    )
    PluginPackage.objects.filter(pk=package.pk).update(
        trust=new_trust,
        signer_public_key=(key if same_signer else "RWQ" + "b" * 53) if new_trust == Trust.TRUSTED else None,
    )

    assert _review(superadmin_client, package)["upgrade"]["trust_change"] == expected


def test_user_permissions_settings_and_limits_changes_are_listed(weather, newer, superadmin_client):
    region = {"key": "region", "type": "string", "label": "Region", "description": "Where.", "required": True}
    package = newer(
        user_permissions=[
            {"action": "read", "description": "Open Weather.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
            {"action": "update", "description": "Edit places.", "defaults": {"org_admin": True, "member": True, "viewer": False}},
        ],
        settings=[dict(UNITS_SETTING), region],
        limits={"memory_mb": 512, "db_connections": 5, "statement_timeout_seconds": 10, "requests_per_minute": 120, "cpu_priority": "normal"},
    )

    upgrade = _review(superadmin_client, package)["upgrade"]

    assert upgrade["user_permissions"] == {"added": ["update"], "removed": [], "defaults_changed": ["read"]}
    assert (upgrade["settings"]["added"], upgrade["settings"]["removed"]) == (["region"], ["forecast_api_token"])
    assert [(needed["key"], needed["reason"]) for needed in upgrade["settings"]["needed"]] == [("region", "required")]
    assert upgrade["limits_changed"] == ["memory_mb"]


def test_a_stored_value_the_new_version_refuses_is_needed_and_a_stored_secret_is_not(weather, newer, superadmin_client, superadmin):
    PluginSettingValue.objects.create(plugin=weather, key="units", value="metric", updated_by=superadmin)
    PluginSettingValue.objects.create(plugin=weather, key="forecast_api_token", encrypted_value="sealed", tail="1234", updated_by=superadmin)
    units = {**UNITS_SETTING, "values": ["si", "us"], "default": "si"}
    package = newer(settings=[units, dict(TOKEN_SETTING)])

    needed = _review(superadmin_client, package)["upgrade"]["settings"]["needed"]

    assert [(row["key"], row["reason"], row["values"]) for row in needed] == [("units", "invalid", ["si", "us"])]


def test_the_baseline_is_an_open_upgrade_s_target(weather, newer, upgrade_of, superadmin_client):
    upgrade = upgrade_of(newer("0.7.0", outbound_hosts=[GEOCODING_HOST, FORECAST_HOST]))
    PluginUpgrade.objects.filter(pk=upgrade.pk).update(failed_at=upgrade.started_at)
    package = newer("0.8.0", outbound_hosts=[GEOCODING_HOST, FORECAST_HOST])

    review = _review(superadmin_client, package)

    assert review["upgrade"]["baseline_package_id"] == upgrade.to_package_id
    assert (review["upgrade"]["from_version"], review["upgrade"]["replaces_version"]) == ("0.6.0", "0.7.0")
    assert review["access_growth"]["requires_acknowledgement"] is False


def test_a_version_that_adds_a_backend_cannot_be_cancelled_and_needs_no_maintenance(running_plugin, installation, superadmin, superadmin_client):
    plugin = running_plugin(version="0.6.0")
    manifest = weather_manifest("0.7.0")

    review = _review(superadmin_client, upload(installation, superadmin, manifest, sample_files(manifest)))

    upgrade = review["upgrade"]
    assert (upgrade["backend"], upgrade["database"], upgrade["maintenance"]) == ("added", "added", False)
    assert (upgrade["cancellable"], upgrade["organizations_going_offline"]) == (False, 0)
    assert upgrade["backup"] == {"required": False, "database_size_bytes": None, "database_name": None}
    assert plugin.current_package.version == "0.6.0"


def test_an_approved_package_has_no_upgrade_review(weather, superadmin_client):
    review = _review(superadmin_client, weather.current_package)

    assert (review["is_upgrade"], review["upgrade"], review["access_growth"]) == (False, None, None)


def test_a_frontend_only_version_is_reviewed_without_maintenance(running_plugin, installation, superadmin, superadmin_client):
    running_plugin(version="0.6.0")
    package = upload(installation, superadmin, sample_manifest(version="0.7.0"))

    upgrade = _review(superadmin_client, package)["upgrade"]

    assert (upgrade["maintenance"], upgrade["backend"], upgrade["database"]) == (False, "unchanged", "none")
