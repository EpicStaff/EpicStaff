"""Backups with pg_dump as plugins_backup, on a real plugins_db (marker `postgres`).

The plugin databases here are hostile on purpose: they hold functions that refuse to run as
anyone but the owner, and settings meant to change how a backup session behaves.
"""

import asyncio
import hashlib
import os
from pathlib import Path

import pytest
from loguru import logger
from psycopg import sql

from es_plugins.database.backup_service import BackupError, BackupRequest
from es_plugins.database.connections import DatabaseConnector, DatabaseUnreachableError
from es_plugins.database.migration_runner import Migration
from es_plugins.database.provisioner import DatabaseProvisioner
from tests.plugin_databases import (
    admin_password,
    backup_password,
    backup_services,
    fetch_all,
    new_app_password,
    owner_session,
    postgres_client_root,
)

pytestmark = pytest.mark.postgres

# Rows behind FORCE ROW LEVEL SECURITY (the owner is subject to it as well), and plugin code that
# fails whoever runs it but the database's owner: a backup that ran any of it would fail.
SCHEMA = """
CREATE SCHEMA app;
CREATE TABLE app.places (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, org_id bigint NOT NULL, name text NOT NULL);
INSERT INTO app.places (org_id, name) SELECT g % 3 + 1, 'p' || g FROM generate_series(1, 30) g;
ALTER TABLE app.places ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.places FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON app.places TO ${app_role}
  USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);
GRANT USAGE ON SCHEMA app TO ${app_role};
GRANT SELECT, INSERT ON app.places TO ${app_role};

CREATE FUNCTION app.guard() RETURNS boolean LANGUAGE plpgsql AS $$ BEGIN
  IF session_user::regrole <> (SELECT datdba FROM pg_database WHERE datname = current_database())::regrole THEN
    RAISE EXCEPTION 'plugin code ran as %', session_user;
  END IF;
  RETURN true;
END $$;
CREATE FUNCTION app.guard_immutable() RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN RETURN app.guard(); END $$;
CREATE TABLE app.guarded (v int DEFAULT 1 CHECK (app.guard()));
CREATE FUNCTION app.guard_trigger() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM app.guard(); RETURN NEW; END $$;
CREATE TRIGGER guarded_trigger BEFORE INSERT ON app.guarded FOR EACH ROW EXECUTE FUNCTION app.guard_trigger();
INSERT INTO app.guarded VALUES (1), (2);
CREATE INDEX guarded_expression ON app.guarded ((app.guard_immutable() AND v > 0));
CREATE POLICY guarded_policy ON app.guarded USING (app.guard());
ALTER TABLE app.guarded ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.guarded FORCE ROW LEVEL SECURITY;
CREATE VIEW app.guard_view AS SELECT app.guard() AS ok;
CREATE MATERIALIZED VIEW app.guard_view_kept AS SELECT app.guard() AS ok;
"""
# Settings the owner may store for its database, each meant to break or turn a backup session.
HOSTILE_SETTINGS = """
DO $$ BEGIN
  EXECUTE format('ALTER DATABASE %I SET role = %L', current_database(), 'pg_read_all_data');
  EXECUTE format('ALTER DATABASE %I SET search_path = %L', current_database(), 'app, public');
  EXECUTE format('ALTER DATABASE %I SET statement_timeout = %L', current_database(), '1ms');
  EXECUTE format('ALTER DATABASE %I SET transaction_timeout = %L', current_database(), '1ms');
  EXECUTE format('ALTER DATABASE %I SET default_transaction_read_only = %L', current_database(), 'on');
  EXECUTE format('ALTER DATABASE %I SET bytea_output = %L', current_database(), 'escape');
  EXECUTE format('ALTER DATABASE %I SET row_security = %L', current_database(), 'on');
END $$;
"""


def migration(name: str, text: str) -> Migration:
    content = text.encode()
    return Migration(name=name, sha256=hashlib.sha256(content).hexdigest(), content=content)


MIGRATIONS = [migration("001_schema.sql", SCHEMA), migration("002_settings.sql", HOSTILE_SETTINGS)]


async def provisioned(plugin_databases, migrations=MIGRATIONS):
    desired = plugin_databases()
    password = new_app_password()
    await DatabaseProvisioner(DatabaseConnector(admin_password())).ensure(
        desired.database_name.removeprefix("plugin_").replace("_", "-"), desired, password, migrations
    )
    return desired, password


def request(desired, plugin="weather", **overrides) -> BackupRequest:
    return BackupRequest(
        **{"plugin": plugin, "database": desired, "upgrade_id": 7, "reason": "pre_upgrade", "version": "0.6.0", **overrides}
    )


def backups_tree(layout) -> list[str]:
    directory = layout.plugin_backups("weather")
    return sorted(os.listdir(directory)) if directory.exists() else []


@pytest.fixture
def client_root(tmp_path):
    return postgres_client_root(tmp_path / "postgres-client")


async def test_a_backup_is_complete_and_described_by_its_metadata(plugin_databases, layout, client_root):
    desired, _ = await provisioned(plugin_databases)
    backups, _, store = backup_services(layout, client_root)

    stored = await backups.backup(request(desired))

    assert backups_tree(layout) == sorted([stored.file_name, stored.file_name.removesuffix(".dump") + ".json"])
    assert store.inventory("weather") == (stored,)
    metadata = stored.metadata
    content = stored.path.read_bytes()
    assert content.startswith(b"PGDMP")
    assert (metadata.size_bytes, metadata.sha256) == (len(content), hashlib.sha256(content).hexdigest())
    assert (metadata.installation_id, metadata.database_name) == (desired.installation_id, desired.database_name)
    assert (metadata.upgrade_id, metadata.reason, metadata.version) == (7, "pre_upgrade", "0.6.0")
    assert metadata.pg_dump_version.startswith("pg_dump (PostgreSQL) 17.")
    assert metadata.server_version.startswith("17.")
    assert [(entry.name, entry.sha256) for entry in metadata.ledger] == [
        (file.name, file.sha256) for file in MIGRATIONS
    ]
    settings = {entry.name: entry.value for entry in metadata.database_settings}
    assert settings["search_path"] == '"app, public"'
    assert settings["role"] == "pg_read_all_data"
    report = stored.report()
    assert (report.file_name, report.sha256, report.installation_id) == (
        stored.file_name,
        metadata.sha256,
        desired.installation_id,
    )


async def test_the_backup_runs_no_plugin_code_whatever_the_database_settings(plugin_databases, layout, client_root):
    # The guard objects fail any session but the owner's, and the stored settings would make a
    # session switch role, time out at once and filter rows: the backup is complete regardless.
    desired, _ = await provisioned(plugin_databases)
    backups, _, _ = backup_services(layout, client_root)

    stored = await backups.backup(request(desired))

    assert stored.metadata.size_bytes > 0
    connector = DatabaseConnector(admin_password())
    async with connector.admin_session(desired.server) as admin:
        assert await fetch_all(admin, "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'evil%'") == [(0,)]


async def test_a_database_the_owner_closed_to_backups_is_opened_again_first(plugin_databases, layout, client_root):
    desired, _ = await provisioned(plugin_databases)
    async with owner_session(desired) as owner:
        await owner.execute(
            sql.SQL("ALTER DATABASE {} IS_TEMPLATE true CONNECTION LIMIT 0").format(sql.Identifier(desired.database_name))
        )
    backups, _, _ = backup_services(layout, client_root)
    lines = []
    sink = logger.add(lines.append, format="{message}", level="WARNING")
    try:
        await backups.backup(request(desired))
    finally:
        logger.remove(sink)

    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        assert await fetch_all(
            admin, "SELECT datistemplate, datconnlimit FROM pg_database WHERE datname = %s", (desired.database_name,)
        ) == [(False, -1)]
    assert any(line.startswith("plugins.database.attributes_reset plugin=weather") for line in lines)


async def test_no_room_for_the_backup_refuses_it_before_dumping(plugin_databases, layout, client_root):
    desired, _ = await provisioned(plugin_databases)
    backups, _, _ = backup_services(layout, client_root, free_bytes=513 * 1024 * 1024)

    with pytest.raises(BackupError, match="not enough disk space for the database backup: about") as refused:
        await backups.backup(request(desired))

    assert refused.value.reason == "disk"
    assert backups_tree(layout) == []


async def test_a_dump_refused_by_the_server_leaves_nothing(plugin_databases, layout, client_root, monkeypatch):
    desired, _ = await provisioned(plugin_databases)
    backups, _, _ = backup_services(layout, client_root)
    monkeypatch.setattr(backups, "_backup_password", "not-" + backup_password())

    with pytest.raises(BackupError) as failed:
        await backups.backup(request(desired))

    assert failed.value.reason == "dump"
    assert "password authentication failed" in str(failed.value)
    assert backups_tree(layout) == []


def tools_with(client_root: Path, tmp_path: Path, name: str, script: str) -> Path:
    """The test server's client tools, with `name` replaced by `script`."""
    root = tmp_path / f"tools-with-{name}"
    (root / "bin").mkdir(parents=True)
    for tool in ("pg_dump", "pg_restore"):
        path = root / "bin" / tool
        path.write_text("#!/bin/sh\n" + script if tool == name else (client_root / "bin" / tool).read_text())
        path.chmod(0o755)
    return root


async def test_a_dump_killed_half_way_leaves_nothing(plugin_databases, layout, client_root, tmp_path):
    desired, _ = await provisioned(plugin_databases)
    root = tools_with(
        client_root,
        tmp_path,
        "pg_dump",
        'if [ "$1" = --version ]; then echo "pg_dump (PostgreSQL) 17.11"; exit 0; fi\n'
        "printf 'PGDMP half'\nkill -9 $$\n",
    )
    backups, _, _ = backup_services(layout, root)

    with pytest.raises(BackupError) as failed:
        await backups.backup(request(desired))

    assert failed.value.reason == "dump"
    assert backups_tree(layout) == []


async def test_a_dump_that_cannot_be_read_back_leaves_nothing(plugin_databases, layout, client_root, tmp_path):
    desired, _ = await provisioned(plugin_databases)
    root = tools_with(client_root, tmp_path, "pg_restore", "cat > /dev/null\necho 'pg_restore: error: corrupt' >&2\nexit 1\n")
    backups, _, _ = backup_services(layout, root)

    with pytest.raises(BackupError) as failed:
        await backups.backup(request(desired))

    assert failed.value.reason == "verify"
    assert backups_tree(layout) == []


async def test_a_crash_before_the_metadata_leaves_nothing_under_a_final_name(plugin_databases, layout, client_root):
    desired, _ = await provisioned(plugin_databases)
    backups, _, store = backup_services(layout, client_root)

    def crash(*arguments):
        raise OSError("No space left on device")

    store.write_metadata = crash
    with pytest.raises(OSError):
        await backups.backup(request(desired))

    assert backups_tree(layout) == []


async def test_a_cancelled_backup_kills_pg_dump_and_leaves_nothing(plugin_databases, layout, client_root, tmp_path):
    desired, _ = await provisioned(plugin_databases)
    root = tools_with(
        client_root,
        tmp_path,
        "pg_dump",
        'if [ "$1" = --version ]; then echo "pg_dump (PostgreSQL) 17.11"; exit 0; fi\n'
        f"echo $$ > '{tmp_path}/pid'\nprintf PGDMP\nexec sleep 60\n",
    )
    backups, _, _ = backup_services(layout, root)
    backup = asyncio.create_task(backups.backup(request(desired)))
    while not (tmp_path / "pid").exists():
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    backup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await backup

    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid").read_text()), 0)
    assert backups_tree(layout) == []


async def test_large_objects_fail_the_backup_saying_why(plugin_databases, layout, client_root):
    desired, _ = await provisioned(
        plugin_databases, [migration("001_blob.sql", "SELECT lo_from_bytea(0, 'binary data');")]
    )
    backups, _, _ = backup_services(layout, client_root)

    with pytest.raises(BackupError, match="holds large objects, which backups cannot read") as failed:
        await backups.backup(request(desired))

    assert failed.value.reason == "dump"
    assert backups_tree(layout) == []


async def test_an_unreachable_server_is_a_failure_that_may_pass(plugin_databases, layout, client_root):
    desired, _ = await provisioned(plugin_databases)
    backups, _, _ = backup_services(layout, client_root)
    unreachable = desired.model_copy(update={"server": desired.server.model_copy(update={"port": 1})})

    with pytest.raises(DatabaseUnreachableError):
        await backups.backup(request(unreachable))


async def test_only_pg_dump_gets_the_backup_password_and_never_in_argv_or_logs(plugin_databases, layout, client_root):
    desired, _ = await provisioned(plugin_databases)
    runs = []

    async def spying(*argv, **options):
        runs.append((argv, options["env"]))
        return await asyncio.create_subprocess_exec(*argv, **options)

    backups, _, _ = backup_services(layout, client_root, create_process=spying)
    lines = []
    sink = logger.add(lines.append, format="{message}", level="DEBUG")
    try:
        await backups.backup(request(desired))
    finally:
        logger.remove(sink)

    password = backup_password()
    tools = [Path(argv[0]).name for argv, _ in runs]
    assert tools.count("pg_dump") == 2  # its version, then the dump
    assert "pg_restore" in tools
    for argv, environment in runs:
        assert not any(password in argument for argument in argv)
        if Path(argv[0]).name == "pg_dump" and "--version" not in argv:
            assert environment["PGPASSWORD"] == password
            assert environment["PGUSER"] == "plugins_backup"
            assert environment["PGREQUIREAUTH"] == "scram-sha-256"
            assert "-c role=none" in environment["PGOPTIONS"] and "-c row_security=off" in environment["PGOPTIONS"]
        else:
            assert "PGPASSWORD" not in environment and "PGUSER" not in environment
    assert not [line for line in lines if password in line or "PGPASSWORD" in line]


async def test_a_pg_dump_that_cannot_run_fails_the_backup(plugin_databases, layout, client_root, tmp_path):
    desired, _ = await provisioned(plugin_databases)
    root = tools_with(client_root, tmp_path, "pg_dump", "exit 127\n")
    backups, _, _ = backup_services(layout, root)

    with pytest.raises(BackupError, match="pg_dump cannot run") as failed:
        await backups.backup(request(desired))

    assert failed.value.reason == "dump"
    assert backups_tree(layout) == []


async def test_only_a_pre_upgrade_backup_must_hold_the_ledger(plugin_databases, layout, client_root):
    desired, _ = await provisioned(plugin_databases)
    async with owner_session(desired) as owner:
        await owner.execute("DROP SCHEMA _epicstaff CASCADE")
    backups, _, _ = backup_services(layout, client_root)

    with pytest.raises(BackupError, match="holds no data of the migration ledger") as refused:
        await backups.backup(request(desired))
    kept = await backups.backup(request(desired, reason="pre_restore", restore_id=3))

    assert refused.value.reason == "verify"
    assert (kept.metadata.reason, kept.metadata.ledger) == ("pre_restore", None)
