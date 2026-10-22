"""Upgrades and restores through the reconciler, stage by stage, as EpicStaff grants them.

Same stand-ins as `test_reconciler`: django_app behind `httpx.MockTransport`, the launcher's
operations without root, a real child process answering the health check. Backups and restores
are recorded (they have their own tests against plugins_db).
"""

import asyncio
import hashlib

import pytest
from src.shared.models.plugin_nodes import LedgerEntry

from es_plugins.agent import reconciler as reconciler_module
from es_plugins.agent import upgrade as upgrade_module
from es_plugins.agent.reconciler import Reconciler
from es_plugins.database.backup_service import BackupError, BackupRequest
from es_plugins.database.connections import DatabaseProvisioningError, DatabaseUnreachableError
from es_plugins.database.restore_service import RestoreError
from es_plugins.node_disk import FLOOR_BYTES
from tests.helpers import backend_wheels, database_section, desired_state, manifest, package_files, sha256_hex, write_package
from tests.test_reconciler import (  # noqa: F401 (fixtures)
    APP_PASSWORD,
    DATABASE_MIGRATIONS,
    UID,
    node,
    package_bytes,
    running,
)
from tests.test_supervisor_backoff import wait_until

pytestmark = pytest.mark.linux

TARGET_MIGRATIONS = {**DATABASE_MIGRATIONS, "003_new.sql": b"ALTER TABLE places ADD COLUMN note text;\n"}


def package_with_migrations(tmp_path, version: str, migrations: dict[str, bytes]) -> bytes:
    files = package_files(backend_wheels(tmp_path / f"wheels-{version}"), {**manifest(version=version), "database": {}})
    files.update({f"database/migrations/{name}": content for name, content in migrations.items()})
    return write_package(tmp_path / f"weather-{version}.esplugin", files, version=version).read_bytes()


def package_section(content: bytes, package_id: int, version: str) -> dict:
    return {
        "package_id": package_id,
        "version": version,
        "sha256": sha256_hex(content),
        "size": len(content),
        "trust": "untrusted",
        "signer_public_key": None,
    }


@pytest.fixture
def upgrading(node, tmp_path):
    reconciler, django, launcher, venv_builder, desired = node
    current = package_with_migrations(tmp_path, "0.2.0", DATABASE_MIGRATIONS)
    target = package_with_migrations(tmp_path, "0.3.0", TARGET_MIGRATIONS)
    newer = package_with_migrations(tmp_path, "0.3.1", TARGET_MIGRATIONS)
    django.packages.update({12: current, 13: target, 14: newer})
    django.database_passwords[7] = APP_PASSWORD
    targets = {13: (target, "0.3.0"), 14: (newer, "0.3.1")}

    def runtime() -> dict:
        return {
            "python": "3.13",
            "entrypoint": "weather_plugin.app:app",
            "port": desired.port,
            "unix_uid": UID,
            "memory_mb": 256,
            "cpu_priority": "normal",
        }

    def state(
        stage=None, *, target_id=13, backup="required", needed=4096, generation=0, restore=None, failed=False, **overrides
    ):
        """The desired state at `stage` of upgrade 5 (None: no upgrade open, the current version)."""
        content, version = targets[target_id]
        if stage in (None, "preparing"):
            package, package_id, package_version = current, 12, "0.2.0"
        else:
            package, package_id, package_version = content, target_id, version
        if stage == "done":
            stage = None
        if stage is not None:
            overrides["upgrade"] = {
                "upgrade_id": 5,
                "stage": stage,
                "from_version": "0.2.0",
                "target": package_section(content, target_id, version),
                "target_runtime": runtime(),
                "backup": backup,
                "backup_bytes_needed": needed if backup == "required" else 0,
                "failed": failed,
            }
        if restore is not None:
            overrides["restore"] = restore
        return desired(
            package,
            package_id=package_id,
            version=package_version,
            database=database_section(),
            restart_generation=generation,
            **overrides,
        )

    advanced = asyncio.Event()
    django.on_advance = lambda upgrade_id, body: advanced.set()
    state.advanced = advanced
    state.services = desired.services
    state.volume = desired.volume
    state.backups = desired.backups
    state.restores = desired.restores
    state.provisioner = desired.provisioner
    state.requests = desired.desired_state_requests
    return reconciler, django, launcher, venv_builder, state


def upgrade_report(reconciler):
    return reconciler.reports()[0].upgrade


def advance_bodies(django) -> list[dict]:
    return [body for upgrade_id, body in django.advances if upgrade_id == 5]


async def run_current(reconciler, state):
    await reconciler.apply(state())
    await wait_until(lambda: running(reconciler))
    return reconciler.reports()[0].pid


async def test_preparing_installs_the_target_beside_the_running_version_and_asks_for_maintenance(upgrading, layout):
    reconciler, django, launcher, venv_builder, state = upgrading
    pid = await run_current(reconciler, state)

    await reconciler.apply(state("preparing"))
    await asyncio.wait_for(state.advanced.wait(), 10)

    assert advance_bodies(django) == [{"to": "maintenance", "backup": None}]
    assert ("install_code", "weather", UID, "0.3.0") in launcher.operations
    assert [request.venv for request in venv_builder.requests][-1] == layout.plugin_venv("weather", "0.3.0")
    report = reconciler.reports()[0]
    assert (report.pid, report.observed_version, report.observed_state) == (pid, "0.2.0", "running")
    assert (report.upgrade.stage, report.upgrade.step, report.upgrade.state) == ("preparing", "backup", "working")
    assert report.upgrade.generation == 0
    assert state.requests, "a granted advance fetches the desired state at once"
    await asyncio.sleep(0.5)
    assert len(advance_bodies(django)) == 1
    downloads = sorted(path.name.split("-")[0] for path in layout.downloads_directory.glob("*.esplugin"))
    assert downloads == ["12", "13"]


async def test_preparing_without_room_for_the_backup_fails_at_backup_and_keeps_running(upgrading):
    reconciler, django, launcher, _, state = upgrading
    pid = await run_current(reconciler, state)
    free = state.volume.free_bytes - FLOOR_BYTES

    await reconciler.apply(state("preparing", needed=free + 1024 * 1024))
    await wait_until(lambda: upgrade_report(reconciler).state == "failed")

    report = reconciler.reports()[0]
    assert report.upgrade.step == "backup"
    assert report.upgrade.last_error == (
        f"not enough disk space for the database backup: about {free // 2**20 + 1} MB needed, {free // 2**20} MB free"
    )
    assert (report.pid, report.observed_state) == (pid, "running")
    assert advance_bodies(django) == []


async def test_a_refused_advance_drops_the_stage_and_the_plugin_keeps_running(upgrading):
    reconciler, django, launcher, _, state = upgrading
    pid = await run_current(reconciler, state)
    django.advance_status = 409

    await reconciler.apply(state("preparing"))
    await wait_until(lambda: advance_bodies(django))
    await asyncio.sleep(0.5)

    assert len(advance_bodies(django)) == 1
    assert reconciler.reports()[0].pid == pid


async def test_maintenance_drains_stops_backs_up_then_asks_for_migrations(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("preparing"))
    await asyncio.wait_for(state.advanced.wait(), 10)
    state.advanced.clear()
    provisions_before = len(state.provisioner.calls)
    spawns_before = len(launcher.spawned)

    await reconciler.apply(state("maintenance"))
    await asyncio.wait_for(state.advanced.wait(), 10)

    steps = [operation[0] for operation in launcher.operations]
    stopped_at = max(index for index, step in enumerate(steps) if step == "kill_uid")
    assert stopped_at < steps.index("backup")
    [request] = state.backups.requests
    assert (request.upgrade_id, request.reason, request.version) == (5, "pre_upgrade", "0.2.0")
    [_, body] = advance_bodies(django)
    assert body["to"] == "migrations"
    assert (body["backup"]["upgrade_id"], body["backup"]["reason"], body["backup"]["version"]) == (5, "pre_upgrade", "0.2.0")
    assert body["backup"]["installation_id"] == database_section()["installation_id"]
    report = reconciler.reports()[0]
    assert report.observed_state == "stopped"
    assert (report.upgrade.stage, report.upgrade.step) == ("maintenance", "backup")
    assert [backup.file_name for backup in report.backups] == [body["backup"]["file_name"]]
    assert len(state.provisioner.calls) == provisions_before
    assert len(launcher.spawned) == spawns_before


async def test_migrating_provisions_with_the_targets_migrations_and_starts_it_then_completion_prunes(upgrading, layout):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django))

    await reconciler.apply(state("migrating", backup="taken"))
    await wait_until(lambda: running(reconciler) and reconciler.reports()[0].observed_version == "0.3.0")

    call = state.provisioner.calls[-1]
    assert sorted(migration.name for migration in call["migrations"]) == sorted(TARGET_MIGRATIONS)
    report = reconciler.reports()[0]
    assert (report.upgrade.stage, report.upgrade.step, report.upgrade.state) == ("migrating", "start", "working")
    assert [(entry.name, entry.sha256) for entry in report.database.ledger] == [
        (name, hashlib.sha256(content).hexdigest()) for name, content in sorted(TARGET_MIGRATIONS.items())
    ]

    await reconciler.apply(state("done"))
    await wait_until(lambda: ("prune_code", "weather", UID, "0.3.0") in launcher.operations)

    assert reconciler.reports()[0].upgrade is None
    await wait_until(lambda: not layout.plugin_venv("weather", "0.2.0").exists())
    assert layout.plugin_venv("weather", "0.3.0").exists()


async def test_a_taken_backup_is_not_taken_again(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)

    await reconciler.apply(state("maintenance", backup="taken"))
    await wait_until(lambda: advance_bodies(django))

    assert state.backups.requests == []
    assert advance_bodies(django) == [{"to": "migrations", "backup": None}]


async def test_a_backup_of_this_upgrade_already_on_the_node_is_used_again(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    database = state("maintenance").placements[0].database
    kept = await state.backups.backup(
        BackupRequest(plugin="weather", database=database, upgrade_id=5, reason="pre_upgrade", version="0.2.0")
    )
    state.backups.requests.clear()

    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django))

    assert state.backups.requests == []
    assert advance_bodies(django)[0]["backup"]["file_name"] == kept.file_name


async def test_a_failed_backup_fails_the_stage_and_nothing_is_migrated(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    state.backups.failures.append(BackupError("dump", "pg_dump exited with status 1: no space"))

    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: upgrade_report(reconciler).state == "failed")

    report = reconciler.reports()[0].upgrade
    assert (report.step, report.last_error) == ("backup", "pg_dump exited with status 1: no space")
    assert advance_bodies(django) == []
    await asyncio.sleep(0.3)
    assert len(state.backups.requests) == 1


async def test_a_backup_failure_that_may_pass_is_tried_again(upgrading, monkeypatch):
    monkeypatch.setattr(upgrade_module, "TRANSIENT_RETRY_SECONDS", 0.2)
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    state.backups.failures.append(DatabaseUnreachableError("plugins_db at plugins_db:5432 cannot be reached"))

    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: upgrade_report(reconciler).last_error is not None)
    assert upgrade_report(reconciler).state == "working"
    await wait_until(lambda: advance_bodies(django), timeout=10)

    assert len(state.backups.requests) == 2


async def test_a_retry_runs_a_failed_stage_again(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    state.backups.failures.append(BackupError("disk", "not enough disk space"))
    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: upgrade_report(reconciler).state == "failed")

    await reconciler.apply(state("maintenance", generation=1))
    await wait_until(lambda: advance_bodies(django))

    assert upgrade_report(reconciler).generation == 1


async def test_a_cancel_during_the_backup_cuts_it_short_and_the_old_version_starts(upgrading, layout):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("preparing"))
    await asyncio.wait_for(state.advanced.wait(), 10)
    state.backups.started, state.backups.hold = asyncio.Event(), asyncio.Event()
    await reconciler.apply(state("maintenance"))
    await asyncio.wait_for(state.backups.started.wait(), 10)

    # Cancelled: the plugin goes back to its current version, with a new restart generation.
    await reconciler.apply(state(generation=1))
    await wait_until(lambda: running(reconciler))

    assert advance_bodies(django) == [{"to": "maintenance", "backup": None}]
    assert reconciler.reports()[0].observed_version == "0.2.0"
    assert reconciler.reports()[0].upgrade is None
    await wait_until(lambda: ("prune_code", "weather", UID, "0.2.0") in launcher.operations)
    await wait_until(lambda: not layout.plugin_venv("weather", "0.3.0").exists())
    # The cancelled target's download goes; the version that runs needs none (it is installed).
    downloads = sorted(path.name.split("-")[0] for path in layout.downloads_directory.glob("*.esplugin"))
    assert "13" not in downloads


async def test_a_cancel_after_the_backup_gets_no_migrations_and_the_old_version_starts(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    django.advance_status = 409

    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django))
    await reconciler.apply(state(generation=1))
    await wait_until(lambda: running(reconciler))

    calls = state.provisioner.calls
    assert sorted(migration.name for migration in calls[-1]["migrations"]) == sorted(DATABASE_MIGRATIONS)


async def test_a_newer_target_is_prepared_while_the_plugin_stays_stopped(upgrading, layout):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django))
    spawns = len(launcher.spawned)

    await reconciler.apply(state("maintenance", target_id=14, backup="taken"))
    await wait_until(lambda: len(advance_bodies(django)) == 2)

    assert ("install_code", "weather", UID, "0.3.1") in launcher.operations
    assert advance_bodies(django)[-1] == {"to": "migrations", "backup": None}
    assert len(state.backups.requests) == 1
    assert len(launcher.spawned) == spawns


@pytest.mark.parametrize("stage", ["preparing", "maintenance", "migrating"])
async def test_an_agent_restart_resumes_the_stage(upgrading, stage):
    # A restarted agent is a new container: nothing of the first one holds the plugin's port, so
    # the first one here never runs the plugin.
    reconciler, django, launcher, _, state = upgrading
    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django))
    await reconciler.close()
    django.advances.clear()
    backups_taken = len(state.backups.requests)

    restarted = Reconciler(state.services)
    try:
        await restarted.apply(state(stage, backup="required" if stage != "migrating" else "taken"))
        if stage == "migrating":
            await wait_until(lambda: running(restarted) and restarted.reports()[0].observed_version == "0.3.0")
        else:
            await wait_until(lambda: advance_bodies(django), timeout=15)
        if stage == "maintenance":
            # The backup takes the database's lock without claiming the database is set up.
            assert restarted.reports()[0].database is None
    finally:
        await restarted.close()

    # The backup this upgrade took is on the node: a restarted maintenance uses it again.
    assert len(state.backups.requests) == backups_taken
    if stage == "maintenance":
        assert advance_bodies(django)[0]["backup"]["upgrade_id"] == 5


async def test_the_drain_lets_the_hook_in_flight_finish_before_the_plugin_stops(upgrading, tmp_path):
    reconciler, django, launcher, _, state = upgrading
    launcher.hook_delay = 1.0
    django.runtime_files[7] = {**django.runtime_files[7], "service_accounts": {"3": {"key": "esp-" + "k" * 40 + "abc", "org_name": "Acme", "grant_state": "upgrading"}}}
    from tests.helpers import hook_invocation, hook_job

    django.hook_invocations[41] = hook_invocation(kind="upgrade")
    await reconciler.apply(state(hook_jobs=[hook_job(kind="upgrade")]))
    await wait_until(lambda: django.requests_to("claim") == [41])

    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django), timeout=15)
    await wait_until(lambda: django.hook_results)

    # Had the stop cut the call short, it would have failed as "stopped during the hook".
    assert django.hook_results[0][1]["outcome"] == "succeeded"


async def test_a_restore_replaces_the_database_starts_nothing_and_is_reported(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django))
    backup_name = advance_bodies(django)[0]["backup"]["file_name"]
    state.provisioner.failures.append(DatabaseProvisioningError("migration", "003_new.sql line 1: [22012] division by zero"))
    await reconciler.apply(state("migrating", backup="taken"))
    await wait_until(lambda: upgrade_report(reconciler).state == "failed")
    assert upgrade_report(reconciler).step == "migrate"
    spawns = len(launcher.spawned)
    restore = {"restore_id": 9, "upgrade_id": 5, "backup_file": backup_name, "backup_sha256": "a" * 64}

    await reconciler.apply(state("migrating", backup="taken", restore=restore))
    await wait_until(lambda: reconciler.reports()[0].restore.state == "succeeded")

    report = reconciler.reports()[0]
    assert report.restore.pre_restore_backup.endswith("-u5-pre_restore.dump")
    assert report.database.ledger == [LedgerEntry(name="001_places.sql", sha256="a" * 64)]
    [call] = state.restores.calls
    assert (call["version"], call["app_password"]) == ("0.3.0", APP_PASSWORD)
    assert len(launcher.spawned) == spawns
    # A Retry provisions the restored database again, migrations included.
    provisions = len(state.provisioner.calls)
    await reconciler.apply(state("migrating", backup="taken", generation=1))
    await wait_until(lambda: len(state.provisioner.calls) > provisions)


async def test_a_restore_that_fails_is_reported_failed_with_its_step(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("maintenance"))
    await wait_until(lambda: advance_bodies(django))
    state.restores.failures.append(RestoreError("restore", "pg_restore exited with status 1: corrupt"))
    restore = {"restore_id": 9, "upgrade_id": 5, "backup_file": advance_bodies(django)[0]["backup"]["file_name"], "backup_sha256": "a" * 64}

    await reconciler.apply(state("migrating", backup="taken", restore=restore))
    await wait_until(lambda: reconciler.reports()[0].restore.state == "failed")

    report = reconciler.reports()[0].restore
    assert (report.step, report.last_error) == ("restore", "pg_restore exited with status 1: corrupt")


async def test_a_failed_migration_reports_the_step_and_the_ledger_it_left(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("maintenance", backup="taken"))
    await wait_until(lambda: advance_bodies(django))
    failure = DatabaseProvisioningError("migration", "003_new.sql line 1: [22012] division by zero")
    failure.ledger = (LedgerEntry(name="001_places.sql", sha256="a" * 64),)
    state.provisioner.failures.append(failure)

    await reconciler.apply(state("migrating", backup="taken"))
    await wait_until(lambda: upgrade_report(reconciler).state == "failed")

    report = reconciler.reports()[0]
    assert (report.upgrade.step, report.upgrade.last_error) == ("migrate", "003_new.sql line 1: [22012] division by zero")
    assert [entry.name for entry in report.database.ledger] == ["001_places.sql"]


async def test_a_target_whose_start_is_refused_fails_at_start(upgrading):
    from es_plugins.agent.launcher_client import LauncherError

    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    await reconciler.apply(state("maintenance", backup="taken"))
    await wait_until(lambda: advance_bodies(django))

    async def refused(plugin, uid, content):
        raise LauncherError("the runtime file cannot be written: test")

    launcher.write_runtime_file = refused

    await reconciler.apply(state("migrating", backup="taken"))
    await wait_until(lambda: upgrade_report(reconciler).state == "failed")

    assert upgrade_report(reconciler).step == "start"


async def test_the_backups_the_desired_state_lists_are_deleted(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await run_current(reconciler, state)
    database = state().placements[0].database
    old = await state.backups.backup(
        BackupRequest(plugin="weather", database=database, upgrade_id=4, reason="pre_upgrade", version="0.1.0")
    )
    kept = await state.backups.backup(
        BackupRequest(plugin="weather", database=database, upgrade_id=5, reason="pre_upgrade", version="0.2.0")
    )

    await reconciler.apply(state(backups_to_delete=[old.file_name]))

    assert [backup.file_name for backup in reconciler.reports()[0].backups] == [kept.file_name]


# A restarted agent: the reconciler of the fixture has run nothing yet, so it starts with no memory
# of the upgrade, as a new container does.


async def test_after_an_agent_restart_a_failed_migrating_upgrade_does_not_run_its_migrations_again(upgrading):
    reconciler, django, launcher, _, state = upgrading

    await reconciler.apply(state("migrating", backup="taken", failed=True))
    await asyncio.sleep(1.0)

    assert state.provisioner.calls == []
    assert launcher.spawned == []
    report = reconciler.reports()[0]
    # Nothing of this upgrade is known to this agent: EpicStaff keeps its step and error.
    assert report.upgrade is None and report.database is None

    # A Retry clears it, with a new restart generation: the migrations run.
    await reconciler.apply(state("migrating", backup="taken", generation=1))
    await wait_until(lambda: state.provisioner.calls)


async def test_a_restore_while_the_upgrade_is_failed_runs_and_is_not_undone(upgrading):
    reconciler, django, launcher, _, state = upgrading
    restore = {"restore_id": 9, "upgrade_id": 5, "backup_file": "20261021T101500Z-u5-pre_upgrade.dump", "backup_sha256": "a" * 64}

    await reconciler.apply(state("migrating", backup="taken", failed=True, restore=restore))
    await wait_until(lambda: reconciler.reports()[0].restore.state == "succeeded")
    # EpicStaff recorded the restore: the upgrade stays failed, with no restore any more.
    await reconciler.apply(state("migrating", backup="taken", failed=True))
    await asyncio.sleep(1.0)

    assert len(state.restores.calls) == 1
    assert state.provisioner.calls == []
    assert launcher.spawned == []
    assert reconciler.reports()[0].database.ledger == [LedgerEntry(name="001_places.sql", sha256="a" * 64)]


async def test_a_failed_maintenance_runs_none_of_its_steps_after_a_restart(upgrading):
    reconciler, django, launcher, _, state = upgrading

    await reconciler.apply(state("maintenance", failed=True))
    await asyncio.sleep(1.0)

    assert not [operation for operation in launcher.operations if operation[0] in ("install_code", "kill_uid", "spawn")]
    assert state.backups.requests == []
    assert advance_bodies(django) == []


async def test_a_failed_preparation_keeps_the_running_version_and_prepares_nothing(upgrading):
    reconciler, django, launcher, _, state = upgrading

    await reconciler.apply(state("preparing", failed=True))
    await wait_until(lambda: running(reconciler))
    await asyncio.sleep(0.5)

    assert reconciler.reports()[0].observed_version == "0.2.0"
    assert ("install_code", "weather", UID, "0.3.0") not in launcher.operations
    assert advance_bodies(django) == []


async def test_a_newer_target_clears_a_failed_stage(upgrading):
    reconciler, django, launcher, _, state = upgrading
    await reconciler.apply(state("maintenance", backup="taken", failed=True))
    await asyncio.sleep(0.5)
    assert advance_bodies(django) == []

    await reconciler.apply(state("maintenance", backup="taken", target_id=14))
    await wait_until(lambda: advance_bodies(django), timeout=15)

    assert ("install_code", "weather", UID, "0.3.1") in launcher.operations

