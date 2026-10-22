"""The backups the node keeps: complete ones listed, listed ones deleted, the rest cleaned up."""

import os
import stat
from datetime import UTC, datetime, timedelta

import pytest
from src.shared.models.plugin_nodes import MAX_BACKUPS_PER_PLACEMENT, backup_file_name

from es_plugins.database.backup_store import (
    METADATA_FORMAT,
    BackupMetadata,
    BackupStore,
    metadata_name,
    temporary_name,
)

CREATED = datetime(2026, 10, 21, 10, 15, tzinfo=UTC)


@pytest.fixture
def store(layout):
    layout.backups_root.mkdir(parents=True, mode=0o700)
    return BackupStore(layout)


def metadata(**overrides) -> BackupMetadata:
    return BackupMetadata(
        **{
            "format": METADATA_FORMAT,
            "plugin": "weather",
            "installation_id": "0123456789abcdef0123456789abcdef",
            "database_name": "plugin_weather",
            "upgrade_id": 7,
            "reason": "pre_upgrade",
            "version": "0.6.0",
            "created_at": CREATED,
            "size_bytes": 5,
            "sha256": "e" * 64,
            "pg_dump_version": "pg_dump (PostgreSQL) 17.11",
            "server_version": "17.11",
            "database_settings": [],
            "ledger": None,
            **overrides,
        }
    )


def backup(store, created_at=CREATED, upgrade_id=7, reason="pre_upgrade", **overrides) -> str:
    """A complete backup, written the way the backup service writes one."""
    name = backup_file_name(created_at, upgrade_id, reason)
    directory = store.directory("weather")
    dump, descriptor = store.create_temporary(directory, name)
    os.write(descriptor, b"PGDMP")
    os.close(descriptor)
    meta = store.write_metadata(
        directory, name, metadata(created_at=created_at, upgrade_id=upgrade_id, reason=reason, **overrides)
    )
    store.publish(directory, dump, meta, name)
    return name


def mode(path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_a_complete_backup_is_listed_with_its_report(store, layout):
    name = backup(store)

    [listed] = store.inventory("weather")

    assert listed.file_name == name == "20261021T101500Z-u7-pre_upgrade.dump"
    report = listed.report()
    assert (report.upgrade_id, report.reason, report.version, report.size_bytes) == (7, "pre_upgrade", "0.6.0", 5)
    directory = layout.plugin_backups("weather")
    assert mode(directory) == 0o700
    assert sorted(os.listdir(directory)) == [name, metadata_name(name)]
    assert {mode(directory / entry) for entry in os.listdir(directory)} == {0o600}


def test_backups_are_listed_newest_first_and_at_most_the_contracts_number(store):
    names = [backup(store, created_at=CREATED + timedelta(minutes=minute)) for minute in range(MAX_BACKUPS_PER_PLACEMENT + 3)]

    listed = [stored.file_name for stored in store.inventory("weather")]

    assert listed == list(reversed(names))[:MAX_BACKUPS_PER_PLACEMENT]


@pytest.mark.parametrize("left", ["dump only", "metadata only", "temporary", "unreadable metadata", "other name"])
def test_only_complete_backups_are_listed_and_the_agent_start_removes_the_rest(store, layout, left):
    kept = backup(store)
    directory = layout.plugin_backups("weather")
    other = backup_file_name(CREATED + timedelta(hours=1), 8, "pre_upgrade")
    if left == "dump only":
        (directory / other).write_bytes(b"PGDMP")
    elif left == "metadata only":
        (directory / metadata_name(other)).write_text(metadata(upgrade_id=8).model_dump_json())
    elif left == "temporary":
        (directory / temporary_name(other)).write_bytes(b"PGDMP half")
    elif left == "unreadable metadata":
        (directory / other).write_bytes(b"PGDMP")
        (directory / metadata_name(other)).write_text('{"format": 1, "plugin"')
    else:
        (directory / "notes.txt").write_text("not a backup")

    assert [stored.file_name for stored in store.inventory("weather")] == [kept]

    store.clean_up()

    assert sorted(os.listdir(directory)) == [kept, metadata_name(kept)]


def test_metadata_that_names_another_upgrade_than_the_file_is_not_a_backup(store, layout):
    name = backup_file_name(CREATED, 7, "pre_upgrade")
    directory = store.directory("weather")
    (directory / name).write_bytes(b"PGDMP")
    (directory / metadata_name(name)).write_text(metadata(upgrade_id=8).model_dump_json())

    assert store.inventory("weather") == ()


def test_only_the_listed_backups_are_deleted_dump_and_metadata(store, layout):
    first = backup(store, created_at=CREATED)
    second = backup(store, created_at=CREATED + timedelta(minutes=1), upgrade_id=8)

    deleted = store.delete("weather", [first, "not-a-backup.dump", "../escape.dump", backup_file_name(CREATED, 99, "pre_restore")])

    assert deleted == [first]
    assert sorted(os.listdir(layout.plugin_backups("weather"))) == [second, metadata_name(second)]
    assert [stored.file_name for stored in store.inventory("weather")] == [second]


def test_a_link_in_place_of_a_backup_is_deleted_and_never_followed(store, layout, tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("someone else's file")
    name = backup_file_name(CREATED, 7, "pre_upgrade")
    directory = store.directory("weather")
    (directory / name).symlink_to(outside)
    (directory / metadata_name(name)).symlink_to(outside)

    assert store.inventory("weather") == ()
    store.delete("weather", [name])

    assert outside.read_text() == "someone else's file"
    assert os.listdir(directory) == []


def test_a_backup_of_the_same_name_is_never_replaced(store):
    name = backup(store)
    directory = store.directory("weather")
    dump, descriptor = store.create_temporary(directory, "x" + name)
    os.close(descriptor)
    meta = store.write_metadata(directory, "x" + name, metadata())

    with pytest.raises(FileExistsError):
        store.publish(directory, dump, meta, name)

    assert store.inventory("weather")[0].path.read_bytes() == b"PGDMP"


def test_a_dump_whose_metadata_cannot_be_published_is_not_left_under_its_name(store, layout):
    name = backup_file_name(CREATED, 7, "pre_upgrade")
    directory = store.directory("weather")
    (directory / metadata_name(name)).write_text("in the way")
    dump, descriptor = store.create_temporary(directory, name)
    os.close(descriptor)
    meta = store.write_metadata(directory, "other.dump", metadata())

    with pytest.raises(FileExistsError):
        store.publish(directory, dump, meta, name)

    assert not (directory / name).exists()


def test_the_inventory_is_read_again_only_when_the_directory_changes(store, monkeypatch):
    backup(store)
    store.inventory("weather")
    reads = []
    real = BackupMetadata.model_validate_json
    monkeypatch.setattr(BackupMetadata, "model_validate_json", lambda content: reads.append(1) or real(content))

    store.inventory("weather")
    assert reads == []

    backup(store, created_at=CREATED + timedelta(minutes=1))
    assert len(store.inventory("weather")) == 2
    assert reads


def test_a_plugin_without_backups_lists_none(store):
    assert store.inventory("weather") == ()
    assert store.delete("weather", [backup_file_name(CREATED, 7, "pre_upgrade")]) == []
