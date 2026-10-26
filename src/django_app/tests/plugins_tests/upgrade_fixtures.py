"""An installed plugin, newer versions of it, and the node's side of an upgrade.

Import the fixtures by name into a test module; the helpers are plain functions.
"""

import hashlib
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.utils import timezone
from plugins.lifecycle.open_upgrades import latest_approved_package, open_upgrade_of
from plugins.models import (
    GrantState,
    HookJobKind,
    Plugin,
    PluginDatabase,
    PluginGrant,
    PluginHookJob,
    PluginPackage,
    PluginPlacement,
    PluginServiceAccount,
    PluginUpgrade,
)
from src.shared.models.plugin_nodes import backup_file_name

from tests.plugins_tests.conftest import mark_running, upload_file
from tests.plugins_tests.package_builder import (
    GEOCODING_HOST,
    backend_manifest,
    build_package,
    sample_files,
)

REPORTS_URL = "/api/plugin-nodes/self/reports/"
SECOND_MIGRATION = "database/migrations/002_conditions.sql"
SECOND_MIGRATION_SQL = b"CREATE TABLE conditions (id bigint PRIMARY KEY, org_id bigint NOT NULL);\n"
FORECAST_HOST = {"host": "api.open-meteo.com", "reason": "Looks up the current temperature."}
DATABASE_SIZE = 4096
TAKEN_AT = datetime(2026, 10, 21, 10, 15, tzinfo=dt_timezone.utc)


def advance_url(upgrade_id: int) -> str:
    return f"/api/plugin-nodes/self/upgrades/{upgrade_id}/advance/"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def weather_manifest(version: str, **changes) -> dict:
    """Weather with a backend and a database, at `version`."""
    changes.setdefault("database", {})
    changes.setdefault("outbound_hosts", [dict(GEOCODING_HOST)])
    return backend_manifest(version=version, **changes)


def version_files(manifest: dict, migrations: dict[str, bytes] | None = None) -> dict[str, bytes]:
    """The files of a package for `manifest`: the sample's, plus `migrations` by path."""
    files = sample_files(manifest)
    files.update(migrations or {})
    return files


def upload(installation, superadmin, manifest: dict, files: dict[str, bytes] | None = None, **build):
    data = build_package(files, manifest=manifest, **build)
    name = f"{manifest['id']}-{manifest['version']}.esplugin"
    return installation.upload(upload_file(data, name), len(data), superadmin)


def baseline_of(plugin: Plugin) -> PluginPackage:
    plugin = Plugin.objects.select_related("current_package").get(pk=plugin.pk)
    return latest_approved_package(plugin, open_upgrade_of(plugin))


def start_upgrade(installation, superadmin, package: PluginPackage, capture, **approval) -> PluginUpgrade:
    """Approve `package` as an upgrade, naming the current baseline unless told otherwise."""
    approval.setdefault("untrusted_acknowledged", True)
    approval.setdefault("access_growth_acknowledged", True)
    approval.setdefault("reviewed_against_package_id", baseline_of(package.plugin).pk)
    with capture(execute=True):
        installation.approve(package.pk, superadmin, **approval)
    return PluginUpgrade.objects.filter(plugin=package.plugin).order_by("-pk").first()


def database_ready(plugin: Plugin, *, size_bytes: int = DATABASE_SIZE) -> PluginDatabase:
    """What the node's first ready report leaves: the current package's files applied."""
    record = PluginDatabase.objects.get(plugin=plugin)
    applied = plugin.current_package.migration_files
    record.state = "ready"
    record.ready_at = timezone.now()
    record.size_bytes = size_bytes
    record.applied_migrations = [file["name"] for file in applied]
    record.ledger = list(applied)
    record.save()
    return record


def active_grant(plugin: Plugin, organization, superadmin, *, version: str | None = None) -> PluginGrant:
    """An active grant brought to `version` (the current one by default), with its account."""
    grant = PluginGrant.objects.create(
        plugin=plugin,
        org=organization,
        state=GrantState.ACTIVE,
        installed_version=version or plugin.current_package.version,
        created_by=superadmin,
    )
    PluginServiceAccount.objects.create(grant=grant)
    return grant


def placement_of(plugin: Plugin) -> PluginPlacement:
    return PluginPlacement.objects.get(plugin=plugin)


def backup_body(upgrade: PluginUpgrade, *, reason: str = "pre_upgrade", version: str | None = None,
                taken_at: datetime = TAKEN_AT, installation_id: str | None = None, sha256: str = "e" * 64,
                upgrade_id: int | None = None) -> dict:
    upgrade_id = upgrade_id or upgrade.pk
    record = PluginDatabase.objects.get(plugin=upgrade.plugin)
    return {
        "file_name": backup_file_name(taken_at, upgrade_id, reason),
        "installation_id": installation_id or record.installation_id,
        "upgrade_id": upgrade_id,
        "reason": reason,
        "version": version or (upgrade.from_version if reason == "pre_upgrade" else upgrade.to_version),
        "size_bytes": DATABASE_SIZE,
        "sha256": sha256,
        "created_at": taken_at.isoformat(),
    }


def send_report(node_client, plugin: Plugin, **observed):
    """Post a report about the plugin's placement; `observed` overrides the entry's fields."""
    placement = placement_of(plugin)
    entry = {
        "placement_id": placement.pk,
        "observed_state": "running",
        "observed_version": plugin.current_package.version,
        "health": "ok",
        "restarts": 0,
        "applied_settings_revision": placement.settings_revision,
        "applied_restart_generation": placement.restart_generation,
        **observed,
    }
    response = node_client.post(
        REPORTS_URL,
        {"format": 1, "agent_version": "0.1.0", "reported_at": "2026-10-21T12:00:05Z", "placements": [entry]},
        format="json",
    )
    assert response.status_code == 204, response.content
    return response


def upgrade_report(upgrade: PluginUpgrade, *, state="working", step="build", last_error=None, **changes) -> dict:
    placement = placement_of(upgrade.plugin)
    upgrade.refresh_from_db()
    return {
        "upgrade_id": upgrade.pk,
        "generation": placement.restart_generation,
        "stage": upgrade.stage,
        "step": step,
        "state": state,
        "last_error": last_error,
        **changes,
    }


def database_report(plugin: Plugin, *, state="ready", ledger=None, **changes) -> dict:
    record = PluginDatabase.objects.get(plugin=plugin)
    ledger = record.ledger if ledger is None else ledger
    return {
        "installation_id": record.installation_id,
        "state": state,
        "applied_migrations": [entry["name"] for entry in ledger],
        "size_bytes": DATABASE_SIZE,
        "ledger": ledger,
        **changes,
    }


def ledger_of(package: PluginPackage, *extra: tuple[str, bytes]) -> list[dict]:
    """The package's files as a ledger, plus `extra` `(name, content)` entries."""
    return [*package.migration_files, *({"name": name, "sha256": digest(content)} for name, content in extra)]


def upgrade_jobs(grant: PluginGrant):
    return PluginHookJob.objects.filter(grant=grant, kind=HookJobKind.UPGRADE).order_by("pk")


@pytest.fixture
def weather(database_plugin, superadmin):
    """Weather 0.6.0, running with its database ready, and no grant yet."""
    plugin = mark_running(database_plugin(version="0.6.0"))
    database_ready(plugin)
    return Plugin.objects.select_related("current_package", "placement").get(pk=plugin.pk)


@pytest.fixture
def newer(installation, superadmin):
    """Factory → a newer Weather uploaded for review, with the second migration."""

    def _make(version="0.7.0", *, migrations=None, files=None, **changes):
        manifest = weather_manifest(version, **changes)
        if files is None:
            files = version_files(
                manifest,
                {SECOND_MIGRATION: SECOND_MIGRATION_SQL} if migrations is None else migrations,
            )
        return upload(installation, superadmin, manifest, files)

    return _make


@pytest.fixture
def upgrade_of(installation, superadmin, django_capture_on_commit_callbacks):
    """Factory → the upgrade an approval of `package` starts."""

    def _start(package, **approval):
        return start_upgrade(installation, superadmin, package, django_capture_on_commit_callbacks, **approval)

    return _start


def ago(**delta) -> datetime:
    return timezone.now() - timedelta(**delta)

