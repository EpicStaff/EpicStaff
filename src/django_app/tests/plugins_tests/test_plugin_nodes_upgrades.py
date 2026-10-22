"""The documents django_app and a plugin node exchange about upgrades, backups and restores."""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.shared.models.plugin_nodes import (
    BACKUP_FILE_NAME_PATTERN,
    MAX_APPLIED_MIGRATIONS,
    MAX_BACKUPS_PER_PLACEMENT,
    MAX_LAST_ERROR_LENGTH,
    BackupFileReport,
    DatabaseReport,
    DesiredPlacement,
    DesiredState,
    NodeReport,
    PlacementReport,
    RestoreReport,
    UpgradeAdvance,
    UpgradeReport,
    backup_file_name,
    database_names_for,
    is_reportable_ledger_entry,
)

INSTALLATION_ID = "0f8c2d4e6a1b3c5d7e9f0a2b4c6d8e0f"
DIGEST = "d" * 64
BACKUP_NAME = "20261021T101500Z-u7-pre_upgrade.dump"


def _package(version="0.6.0", package_id=1):
    return {
        "package_id": package_id,
        "version": version,
        "sha256": "a" * 64,
        "size": 1024,
        "trust": "trusted",
        "signer_public_key": "RWQ" + "x" * 53,
    }


def _runtime(**changes):
    return {
        "python": "3.12",
        "entrypoint": "plugin.app:app",
        "port": 20001,
        "unix_uid": 20000,
        "memory_mb": 256,
        "cpu_priority": "normal",
        **changes,
    }


def _upgrade(stage="preparing", **changes):
    return {
        "upgrade_id": 7,
        "stage": stage,
        "from_version": "0.6.0",
        "target": _package("0.7.0", package_id=2),
        "target_runtime": _runtime(memory_mb=512),
        "backup": "required",
        "backup_bytes_needed": 4096,
        **changes,
    }


def _database():
    names = database_names_for("weather")
    return {
        "server": {"name": "plugins_db", "host": "plugins_db", "port": 5432},
        "installation_id": INSTALLATION_ID,
        "database_name": names.database,
        "owner_role": names.owner_role,
        "app_role": names.app_role,
        "job_role": names.job_role,
        "connection_limit": 3,
        "statement_timeout_seconds": 10,
    }


def _placement(upgrade=None, **changes):
    stopped_for_upgrade = upgrade is not None and upgrade["stage"] != "preparing"
    placement = {
        "placement_id": 1,
        "plugin_identifier": "weather",
        "desired_state": "running",
        "restart_generation": 0,
        "package": upgrade["target"] if stopped_for_upgrade else _package(),
        "runtime": upgrade["target_runtime"] if stopped_for_upgrade else _runtime(),
        "credentials_revision": "b" * 64,
        "settings_revision": 0,
        "database": _database(),
        **changes,
    }
    if upgrade is not None:
        placement["upgrade"] = upgrade
    return placement


def _restore(**changes):
    return {
        "restore_id": 3,
        "upgrade_id": 7,
        "backup_file": BACKUP_NAME,
        "backup_sha256": DIGEST,
        **changes,
    }


def _backup(**changes):
    return {
        "file_name": BACKUP_NAME,
        "installation_id": INSTALLATION_ID,
        "upgrade_id": 7,
        "reason": "pre_upgrade",
        "version": "0.6.0",
        "size_bytes": 4096,
        "sha256": DIGEST,
        "created_at": "2026-10-21T10:15:00.250Z",
        **changes,
    }


def _upgrade_report(**changes):
    return {
        "upgrade_id": 7,
        "generation": 2,
        "stage": "maintenance",
        "step": "backup",
        "state": "working",
        **changes,
    }


def _placement_report(**changes):
    return {
        "placement_id": 1,
        "observed_state": "stopped",
        "health": "unknown",
        "restarts": 0,
        **changes,
    }


def _database_report(**changes):
    return {
        "installation_id": INSTALLATION_ID,
        "state": "ready",
        "applied_migrations": ["001_weather.sql"],
        **changes,
    }


@pytest.mark.parametrize(
    "name",
    [
        BACKUP_NAME,
        "20261021T101500Z-u1-pre_restore.dump",
        "20261021T101500Z-u9223372036854775807-pre_upgrade.dump",
    ],
)
def test_a_backup_file_name_names_its_time_upgrade_and_reason(name):
    assert BackupFileReport.model_validate(
        _backup(
            file_name=name,
            upgrade_id=int(name.split("-u")[1].split("-")[0]),
            reason="pre_restore" if "pre_restore" in name else "pre_upgrade",
        )
    ).file_name == name


@pytest.mark.parametrize(
    "name",
    [
        "20261021T101500-u7-pre_upgrade.dump",
        "20261021T101500Z-u0-pre_upgrade.dump",
        "20261021T101500Z-u07-pre_upgrade.dump",
        "20261021T101500Z-u12345678901234567890-pre_upgrade.dump",
        "20261021T101500Z-u7-before_upgrade.dump",
        "20261021T101500Z-u7-pre_upgrade.dump.json",
        "20261021T101500Z-u7-pre_upgrade.dump\n",
        "../20261021T101500Z-u7-pre_upgrade.dump",
        "weather/20261021T101500Z-u7-pre_upgrade.dump",
    ],
)
def test_anything_else_is_not_a_backup_file_name(name):
    with pytest.raises(ValidationError):
        DesiredPlacement.model_validate(_placement(backups_to_delete=[name]))


def test_a_backup_file_name_is_built_in_utc_to_the_second():
    taken = datetime(2026, 10, 21, 13, 15, 0, 750_000, tzinfo=timezone(timedelta(hours=3)))

    assert backup_file_name(taken, 7, "pre_upgrade") == BACKUP_NAME


def test_a_built_name_is_one_a_backup_report_accepts():
    taken = datetime(2026, 10, 21, 10, 15, tzinfo=UTC)

    report = BackupFileReport.model_validate(
        _backup(file_name=backup_file_name(taken, 7, "pre_restore"), reason="pre_restore")
    )

    assert report.file_name == "20261021T101500Z-u7-pre_restore.dump"


@pytest.mark.parametrize(
    ("created_at", "upgrade_id", "reason"),
    [
        (datetime(2026, 10, 21, 10, 15), 7, "pre_upgrade"),
        (datetime(2026, 10, 21, 10, 15, tzinfo=UTC), 0, "pre_upgrade"),
        (datetime(2026, 10, 21, 10, 15, tzinfo=UTC), 10**19, "pre_upgrade"),
        (datetime(2026, 10, 21, 10, 15, tzinfo=UTC), 7, "nightly"),
    ],
)
def test_a_backup_file_name_is_not_built_from_values_the_pattern_refuses(
    created_at, upgrade_id, reason
):
    with pytest.raises(ValueError):
        backup_file_name(created_at, upgrade_id, reason)


def test_the_pattern_s_groups_are_the_upgrade_id_and_the_reason():
    match = re.fullmatch(BACKUP_FILE_NAME_PATTERN, BACKUP_NAME)

    assert match.groups() == ("7", "pre_upgrade")


@pytest.mark.parametrize(
    "changes",
    [{"upgrade_id": 8}, {"reason": "pre_restore"}],
)
def test_a_backup_whose_name_names_another_upgrade_or_reason_is_refused(changes):
    with pytest.raises(ValidationError, match="names another upgrade or reason"):
        BackupFileReport.model_validate(_backup(**changes))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("size_bytes", 0),
        ("sha256", "D" * 64),
        ("installation_id", "not-an-installation"),
        ("created_at", "2026-10-21T10:15:00"),
    ],
)
def test_a_backup_with_an_invalid_field_is_refused(field, value):
    with pytest.raises(ValidationError):
        BackupFileReport.model_validate(_backup(**{field: value}))


def test_a_ledger_entry_is_reportable_with_a_package_migration_name_and_a_hex_digest():
    assert is_reportable_ledger_entry("001_weather.sql", DIGEST)


@pytest.mark.parametrize(
    ("name", "sha256"),
    [
        ("001_weather.sql", "D" * 64),
        ("001_weather.sql", "d" * 63),
        ("001_weather.sql", "g" * 64),
        ("001_weather.sql", None),
        ("001_weather.sql", b"d" * 64),
        ("001_weather.sql", 1),
        ("1_weather.sql", DIGEST),
        (None, DIGEST),
        (1, DIGEST),
        ("001_" + "a" * 248 + ".sql", DIGEST),
    ],
)
def test_a_ledger_entry_a_plugin_could_have_written_is_not_reportable(name, sha256):
    assert not is_reportable_ledger_entry(name, sha256)


def test_a_database_report_from_an_older_node_has_not_read_the_ledger():
    report = DatabaseReport.model_validate(_database_report())

    assert report.ledger is None


def test_a_failed_database_report_still_carries_the_ledger_it_read():
    report = DatabaseReport.model_validate(
        _database_report(
            state="failed",
            last_error="005_broken.sql line 1: [22012] division by zero",
            ledger=[
                {"name": "001_weather.sql", "sha256": "1" * 64},
                {"name": "004_place_notes.sql", "sha256": "4" * 64},
            ],
        )
    )

    assert [(entry.name, entry.sha256) for entry in report.ledger] == [
        ("001_weather.sql", "1" * 64),
        ("004_place_notes.sql", "4" * 64),
    ]


def test_an_empty_ledger_is_an_empty_list_not_an_unread_one():
    report = DatabaseReport.model_validate(_database_report(ledger=[]))

    assert report.ledger == []


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "001_weather.sql", "sha256": "D" * 64},
        {"name": "001_Weather.sql", "sha256": DIGEST},
        {"name": "001_weather.sql"},
    ],
)
def test_a_report_refuses_a_ledger_entry_that_is_not_reportable(entry):
    with pytest.raises(ValidationError):
        DatabaseReport.model_validate(_database_report(ledger=[entry]))


def test_a_ledger_holds_at_most_as_many_entries_as_a_package_has_migration_numbers():
    entries = [{"name": f"{number:03d}_m.sql", "sha256": DIGEST} for number in range(1000)]

    assert len(DatabaseReport.model_validate(_database_report(ledger=entries)).ledger) == (
        MAX_APPLIED_MIGRATIONS
    )
    with pytest.raises(ValidationError):
        DatabaseReport.model_validate(_database_report(ledger=[*entries, entries[0]]))


def test_a_desired_state_from_an_older_server_has_no_upgrade_restore_or_backups_to_delete():
    placement = DesiredPlacement.model_validate(_placement())

    assert (placement.upgrade, placement.restore, placement.backups_to_delete) == (None, None, [])


def test_while_preparing_the_placement_runs_the_current_version_next_to_the_target():
    placement = DesiredPlacement.model_validate(
        _placement(
            upgrade=_upgrade(),
            hook_jobs=[{"job_id": 4, "kind": "upgrade", "organization_id": 9}],
        )
    )

    assert (placement.package.version, placement.upgrade.target.version) == ("0.6.0", "0.7.0")
    assert placement.hook_jobs[0].kind == "upgrade"


def test_while_preparing_the_target_is_never_the_placement_s_package():
    upgrade = _upgrade()

    with pytest.raises(ValidationError, match="package is the running version"):
        DesiredPlacement.model_validate(_placement(upgrade=upgrade, package=upgrade["target"]))


@pytest.mark.parametrize("stage", ["maintenance", "migrating"])
def test_from_maintenance_on_the_placement_runs_the_target(stage):
    placement = DesiredPlacement.model_validate(_placement(upgrade=_upgrade(stage)))

    assert placement.package == placement.upgrade.target
    assert placement.runtime == placement.upgrade.target_runtime


@pytest.mark.parametrize(
    "changes",
    [{"package": _package()}, {"runtime": _runtime()}],
)
def test_from_maintenance_on_a_package_or_runtime_other_than_the_target_s_is_refused(changes):
    with pytest.raises(ValidationError, match="are the target's"):
        DesiredPlacement.model_validate(_placement(upgrade=_upgrade("maintenance"), **changes))


@pytest.mark.parametrize("stage", ["maintenance", "migrating"])
def test_no_hook_job_is_listed_while_the_plugin_is_stopped_for_an_upgrade(stage):
    with pytest.raises(ValidationError, match="no hook job is listed"):
        DesiredPlacement.model_validate(
            _placement(
                upgrade=_upgrade(stage),
                hook_jobs=[{"job_id": 4, "kind": "install", "organization_id": 9}],
            )
        )


@pytest.mark.parametrize("stage", ["preparing", "maintenance"])
@pytest.mark.parametrize("field", ["port", "unix_uid"])
def test_an_upgrade_never_moves_the_placement_to_another_port_or_user(stage, field):
    upgrade = _upgrade(stage, target_runtime=_runtime(**{field: 20999}))

    with pytest.raises(ValidationError, match="port and user id"):
        DesiredPlacement.model_validate(_placement(upgrade=upgrade, runtime=_runtime()))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage", "done"),
        ("backup", "maybe"),
        ("backup_bytes_needed", -1),
        ("upgrade_id", 0),
    ],
)
def test_an_upgrade_with_an_invalid_field_is_refused(field, value):
    with pytest.raises(ValidationError):
        DesiredPlacement.model_validate(_placement(upgrade=_upgrade(**{field: value})))


def test_a_restore_of_the_open_upgrade_s_backup_is_asked_for_while_migrating():
    placement = DesiredPlacement.model_validate(
        _placement(upgrade=_upgrade("migrating", backup="taken"), restore=_restore())
    )

    assert placement.restore.backup_file == BACKUP_NAME


@pytest.mark.parametrize(
    ("upgrade", "restore"),
    [
        (None, _restore()),
        (_upgrade("maintenance"), _restore()),
        (_upgrade("migrating"), _restore(upgrade_id=8)),
    ],
)
def test_a_restore_outside_the_open_upgrade_s_migrating_stage_is_refused(upgrade, restore):
    with pytest.raises(ValidationError, match="belongs to the open upgrade"):
        DesiredPlacement.model_validate(_placement(upgrade=upgrade, restore=restore))


def test_a_restore_needs_the_placement_s_database():
    with pytest.raises(ValidationError, match="needs the placement's database"):
        DesiredPlacement.model_validate(
            _placement(upgrade=_upgrade("migrating"), restore=_restore(), database=None)
        )


def test_the_backup_being_restored_is_never_also_deleted():
    with pytest.raises(ValidationError, match="cannot be deleted"):
        DesiredPlacement.model_validate(
            _placement(
                upgrade=_upgrade("migrating"),
                restore=_restore(),
                backups_to_delete=[BACKUP_NAME],
            )
        )


def test_a_placement_asks_to_delete_at_most_the_backups_a_node_reports():
    names = [
        f"20261021T1015{second:02d}Z-u7-pre_restore.dump"
        for second in range(MAX_BACKUPS_PER_PLACEMENT)
    ]

    assert len(DesiredPlacement.model_validate(_placement(backups_to_delete=names)).backups_to_delete) == (
        MAX_BACKUPS_PER_PLACEMENT
    )
    with pytest.raises(ValidationError):
        DesiredPlacement.model_validate(
            _placement(backups_to_delete=[*names, "20261021T101600Z-u7-pre_restore.dump"])
        )


def test_a_newer_server_adding_fields_inside_the_upgrade_sections_is_read_leniently():
    placement = _placement(upgrade={**_upgrade("migrating"), "eta_seconds": 30})
    placement["restore"] = {**_restore(), "priority": "high"}
    state = {
        "format": 1,
        "node": {"name": "node-1"},
        "revision": "c" * 64,
        "generated_at": "2026-10-21T10:00:00Z",
        "placements": [placement],
    }

    read = DesiredState.model_validate(state, extra="ignore")

    assert read.placements[0].restore.restore_id == 3


def test_the_upgrade_rules_still_apply_when_the_desired_state_is_read_leniently():
    upgrade = _upgrade()
    state = {
        "format": 1,
        "node": {"name": "node-1"},
        "revision": "c" * 64,
        "generated_at": "2026-10-21T10:00:00Z",
        "placements": [_placement(upgrade=upgrade, package=upgrade["target"])],
    }

    with pytest.raises(ValidationError, match="package is the running version"):
        DesiredState.model_validate(state, extra="ignore")


def test_a_placement_report_from_an_older_node_has_no_upgrade_restore_or_backups():
    report = PlacementReport.model_validate(_placement_report())

    assert (report.upgrade, report.restore, report.backups) == (None, None, [])


def test_a_placement_report_carries_the_upgrade_the_restore_and_the_backups():
    report = PlacementReport.model_validate(
        _placement_report(
            upgrade=_upgrade_report(state="failed", step="migrate", last_error="boom"),
            restore={
                "restore_id": 3,
                "state": "succeeded",
                "step": "assert",
                "pre_restore_backup": "20261021T110000Z-u7-pre_restore.dump",
            },
            backups=[_backup()],
        )
    )

    assert (report.upgrade.generation, report.upgrade.state, report.upgrade.step) == (
        2,
        "failed",
        "migrate",
    )
    assert report.restore.pre_restore_backup == "20261021T110000Z-u7-pre_restore.dump"
    assert report.backups[0].created_at == datetime(2026, 10, 21, 10, 15, 0, 250_000, tzinfo=UTC)


def test_an_upgrade_report_names_the_generation_it_works_to():
    report = {key: value for key, value in _upgrade_report().items() if key != "generation"}

    with pytest.raises(ValidationError):
        UpgradeReport.model_validate(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage", "done"),
        ("step", "unpack"),
        ("state", "succeeded"),
        ("generation", -1),
        ("last_error", "x" * (MAX_LAST_ERROR_LENGTH + 1)),
    ],
)
def test_an_upgrade_report_with_an_invalid_field_is_refused(field, value):
    with pytest.raises(ValidationError):
        UpgradeReport.model_validate(_upgrade_report(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "pending"),
        ("step", "drop"),
        ("pre_restore_backup", "backup.dump"),
    ],
)
def test_a_restore_report_with_an_invalid_field_is_refused(field, value):
    with pytest.raises(ValidationError):
        RestoreReport.model_validate(
            {"restore_id": 3, "state": "running", "step": "verify", field: value}
        )


def test_a_report_lists_at_most_the_backups_a_placement_may_hold():
    backups = [_backup() for _ in range(MAX_BACKUPS_PER_PLACEMENT + 1)]

    with pytest.raises(ValidationError):
        PlacementReport.model_validate(_placement_report(backups=backups))


def test_a_report_from_a_newer_node_is_read_leniently_inside_the_upgrade_sections():
    report = {
        "format": 1,
        "agent_version": "1.0.0",
        "reported_at": "2026-10-21T10:00:00Z",
        "placements": [
            _placement_report(
                upgrade={**_upgrade_report(), "progress": 0.5},
                backups=[{**_backup(), "compression": "zstd"}],
                database={
                    **_database_report(),
                    "ledger": [{"name": "001_weather.sql", "sha256": DIGEST, "applied_at": "x"}],
                },
            )
        ],
    }

    read = NodeReport.model_validate(report, extra="ignore")

    assert read.placements[0].database.ledger[0].name == "001_weather.sql"


def test_the_node_asks_for_maintenance_without_a_backup():
    assert UpgradeAdvance.model_validate({"to": "maintenance"}).backup is None


def test_the_node_asks_for_migrations_with_the_backup_it_took_or_without_one():
    with_backup = UpgradeAdvance.model_validate({"to": "migrations", "backup": _backup()})
    without = UpgradeAdvance.model_validate({"to": "migrations"})

    assert (with_backup.backup.file_name, without.backup) == (BACKUP_NAME, None)


def test_a_backup_never_comes_with_the_request_for_maintenance():
    with pytest.raises(ValidationError, match="only with the request for migrations"):
        UpgradeAdvance.model_validate({"to": "maintenance", "backup": _backup()})


@pytest.mark.parametrize("to", ["migrating", "done", ""])
def test_the_node_asks_only_for_the_next_two_stages(to):
    with pytest.raises(ValidationError):
        UpgradeAdvance.model_validate({"to": to})


def test_an_upgrade_says_whether_its_stage_failed_and_reads_as_not_failed_from_an_older_server():
    failed = DesiredPlacement.model_validate(_placement(upgrade=_upgrade("migrating", failed=True)))
    older = DesiredPlacement.model_validate(_placement(upgrade=_upgrade("migrating")))

    assert (failed.upgrade.failed, older.upgrade.failed) == (True, False)


def test_a_restore_is_asked_for_while_the_stage_is_failed():
    placement = DesiredPlacement.model_validate(
        _placement(upgrade=_upgrade("migrating", backup="taken", failed=True), restore=_restore())
    )

    assert (placement.upgrade.failed, placement.restore.restore_id) == (True, 3)
