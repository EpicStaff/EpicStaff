"""Restores with the owner as the session user, on a real plugins_db (marker `postgres`)."""

import hashlib
import json

import psycopg
import pytest
from psycopg import sql
from src.shared.models.plugin_nodes import DesiredRestore

from es_plugins.database.backup_service import BackupRequest
from es_plugins.database.backup_store import metadata_name
from es_plugins.database.connections import DatabaseConnector
from es_plugins.database.installation_lookup import installation_marker
from es_plugins.database.migration_runner import Migration
from es_plugins.database.provisioner import DatabaseProvisioner
from es_plugins.database.restore_service import RestoreError
from tests.plugin_databases import (
    ConnectionSpy,
    admin_password,
    backup_services,
    catalog_snapshot,
    connect_as,
    fetch_all,
    new_app_password,
    owner_session,
    postgres_client_root,
)

pytestmark = pytest.mark.postgres

SCHEMA = """
CREATE SCHEMA app;
CREATE TABLE app.places (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, org_id bigint NOT NULL, name text NOT NULL);
INSERT INTO app.places (org_id, name) SELECT g % 3 + 1, 'p' || g FROM generate_series(1, 30) g;
ALTER TABLE app.places ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.places FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON app.places TO ${app_role}
  USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint)
  WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);
CREATE MATERIALIZED VIEW app.counts AS SELECT org_id, count(*) AS places FROM app.places GROUP BY org_id;
GRANT USAGE ON SCHEMA app TO ${app_role};
GRANT SELECT, INSERT, DELETE ON app.places TO ${app_role};
GRANT USAGE ON SEQUENCE app.places_id_seq TO ${app_role};

-- Who runs plugin code during a restore, and what it tries.
CREATE TABLE app.ran (session_user_name text, current_user_name text, what text);
CREATE FUNCTION app.spy(what text) RETURNS boolean LANGUAGE plpgsql AS $$ BEGIN
  INSERT INTO app.ran VALUES (session_user, current_user, what);
  BEGIN EXECUTE 'RESET ROLE'; EXCEPTION WHEN others THEN NULL; END;
  BEGIN EXECUTE 'CREATE ROLE restore_evil'; EXCEPTION WHEN others THEN NULL; END;
  BEGIN EXECUTE 'SET ROLE plugins_admin'; EXCEPTION WHEN others THEN NULL; END;
  BEGIN EXECUTE 'CREATE ROLE restore_evil_admin'; EXCEPTION WHEN others THEN NULL; END;
  RETURN true;
END $$;
CREATE FUNCTION app.spy_immutable(what text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN RETURN app.spy(what); END $$;
CREATE TABLE app.checked (v int CHECK (app.spy('check')));
INSERT INTO app.checked VALUES (1), (2);
CREATE INDEX checked_expression ON app.checked ((app.spy_immutable('index') AND v > 0));
DELETE FROM app.ran;

DO $$ BEGIN
  EXECUTE format('ALTER DATABASE %I SET search_path = app, public', current_database());
  EXECUTE format('ALTER DATABASE %I SET statement_timeout = %L', current_database(), '7s');
END $$;
"""
# A newer version's migration that changes the database. FORCE applies to the owner too, so it
# lifts FORCE for its own transaction to reach the rows.
CHANGE = (
    "ALTER TABLE app.places ADD COLUMN note text; ALTER TABLE app.places NO FORCE ROW LEVEL SECURITY; "
    "DELETE FROM app.places WHERE id > 20; ALTER TABLE app.places FORCE ROW LEVEL SECURITY;"
)


def migration(name: str, text: str) -> Migration:
    content = text.encode()
    return Migration(name=name, sha256=hashlib.sha256(content).hexdigest(), content=content)


@pytest.fixture
def client_root(tmp_path):
    return postgres_client_root(tmp_path / "postgres-client")


@pytest.fixture
async def plugin(plugin_databases, layout, client_root):
    """A provisioned plugin database with a pre-upgrade backup, then changed by a newer migration."""
    desired = plugin_databases()
    password = new_app_password()
    provisioner = DatabaseProvisioner(DatabaseConnector(admin_password()))
    await provisioner.ensure("weather", desired, password, [migration("001_schema.sql", SCHEMA)])
    backups, restores, store = backup_services(layout, client_root)
    backup = await backups.backup(
        BackupRequest(plugin="weather", database=desired, upgrade_id=7, reason="pre_upgrade", version="0.6.0")
    )
    await provisioner.ensure(
        "weather", desired, password, [migration("001_schema.sql", SCHEMA), migration("002_change.sql", CHANGE)]
    )
    return desired, password, backup, restores, store


def restore_of(backup, restore_id=3) -> DesiredRestore:
    return DesiredRestore(
        restore_id=restore_id, upgrade_id=7, backup_file=backup.file_name, backup_sha256=backup.metadata.sha256
    )


async def run_restore(restores, desired, password, restore, steps=None):
    return await restores.restore(
        "weather",
        desired,
        restore,
        version="0.7.0",
        app_password=password,
        on_step=lambda step, pre_restore: steps.append(step) if steps is not None else None,
    )


async def place_count(desired, password) -> int:
    app = await connect_as(desired.app_role, password, desired.database_name)
    try:
        total = 0
        for organization_id in (1, 2, 3):
            async with app.transaction():
                await app.execute("SELECT pg_catalog.set_config('app.org_id', %s, true)", (str(organization_id),))
                total += (await fetch_all(app, "SELECT count(*) FROM app.places"))[0][0]
        return total
    finally:
        await app.close()


async def ledger_names(desired) -> list[str]:
    async with owner_session(desired) as owner:
        return [row[0] for row in await fetch_all(owner, "SELECT name FROM _epicstaff.migrations ORDER BY name")]


async def test_a_restore_brings_back_the_data_ledger_and_settings_and_the_app_can_log_in(plugin):
    desired, password, backup, restores, store = plugin
    assert await place_count(desired, password) == 20
    steps = []

    outcome = await run_restore(restores, desired, password, restore_of(backup), steps)

    assert steps == ["verify", "backup", "close", "recreate", "restore", "settings", "assert"]
    assert await place_count(desired, password) == 30
    assert await ledger_names(desired) == ["001_schema.sql"]
    assert [entry.name for entry in outcome.provisioned.ledger] == ["001_schema.sql"]
    async with owner_session(desired) as owner:
        columns = await fetch_all(
            owner, "SELECT column_name FROM information_schema.columns WHERE table_name = 'places' AND column_name = 'note'"
        )
        forced = await fetch_all(owner, "SELECT relforcerowsecurity FROM pg_class WHERE oid = 'app.places'::regclass")
    assert columns == [] and forced == [(True,)]
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        settings = await fetch_all(
            admin,
            "SELECT setconfig FROM pg_db_role_setting WHERE setrole = 0 "
            "AND setdatabase = (SELECT oid FROM pg_database WHERE datname = %s)",
            (desired.database_name,),
        )
    assert sorted(settings[0][0]) == ["search_path=app, public", "statement_timeout=7s"]
    app = await connect_as(desired.app_role, password, desired.database_name)
    try:
        assert await fetch_all(app, "SHOW search_path") == [("app, public",)]
    finally:
        await app.close()


async def test_plugin_code_in_the_dump_runs_as_the_owner_and_cannot_leave_it(plugin):
    desired, password, backup, restores, _ = plugin

    await run_restore(restores, desired, password, restore_of(backup))

    async with owner_session(desired) as owner:
        ran = await fetch_all(owner, "SELECT DISTINCT session_user_name, current_user_name FROM app.ran")
        what = {row[0] for row in await fetch_all(owner, "SELECT what FROM app.ran")}
    assert ran == [(desired.owner_role, desired.owner_role)]
    assert what == {"check", "index"}
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        assert await fetch_all(admin, "SELECT rolname FROM pg_roles WHERE rolname LIKE 'restore_evil%'") == []


async def test_the_pre_restore_backup_comes_first_and_is_used_again_by_the_same_restore(plugin):
    desired, password, backup, restores, store = plugin

    first = await run_restore(restores, desired, password, restore_of(backup))
    second = await run_restore(restores, desired, password, restore_of(backup))

    assert first.pre_restore.metadata.reason == "pre_restore"
    assert first.pre_restore.metadata.restore_id == 3
    assert first.pre_restore.metadata.version == "0.7.0"
    assert [entry.name for entry in first.pre_restore.metadata.ledger] == ["001_schema.sql", "002_change.sql"]
    assert second.pre_restore.file_name == first.pre_restore.file_name
    assert len([stored for stored in store.inventory("weather") if stored.metadata.reason == "pre_restore"]) == 1


async def test_a_restore_that_fails_leaves_an_empty_database_and_the_pre_restore_backup_undoes_it(plugin, layout):
    desired, password, backup, restores, store = plugin
    # Cut the end of the dump's data: pg_restore --list still reads its table of contents, the
    # restore fails on the last table's data.
    content = backup.path.read_bytes()
    cut_length = len(content) - 64
    backup.path.write_bytes(content[:cut_length])
    metadata_path = backup.path.with_name(metadata_name(backup.file_name))
    tampered = json.loads(metadata_path.read_text())
    tampered["sha256"] = hashlib.sha256(backup.path.read_bytes()).hexdigest()
    tampered["size_bytes"] = cut_length
    metadata_path.write_text(json.dumps(tampered))
    cut = store.find("weather", backup.file_name)

    with pytest.raises(RestoreError) as failed:
        await run_restore(restores, desired, password, restore_of(cut))

    assert failed.value.step == "restore" and not failed.value.temporary
    async with owner_session(desired) as owner:
        assert await fetch_all(
            owner, "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
        ) == [(0,)]
    assert await owner_closed(desired)
    [pre_restore] = [stored for stored in store.inventory("weather") if stored.metadata.reason == "pre_restore"]

    await run_restore(restores, desired, password, restore_of(pre_restore, restore_id=4))

    assert await place_count(desired, password) == 20
    assert await ledger_names(desired) == ["001_schema.sql", "002_change.sql"]


async def owner_closed(desired) -> bool:
    owner = next(role for role in (await catalog_snapshot(desired))["roles"] if role[0] == desired.owner_role)
    return (owner[6], owner[7], owner[8]) == (False, -1, "infinity")


@pytest.mark.parametrize("wrong", ["sha256", "installation", "marker"])
async def test_a_restore_that_is_not_this_installations_changes_nothing(plugin, layout, wrong):
    desired, password, backup, restores, store = plugin
    restore = restore_of(backup)
    if wrong == "sha256":
        restore = restore.model_copy(update={"backup_sha256": "0" * 64})
    elif wrong == "installation":
        metadata_path = backup.path.with_name(metadata_name(backup.file_name))
        tampered = json.loads(metadata_path.read_text())
        tampered["installation_id"] = "f" * 32
        metadata_path.write_text(json.dumps(tampered))
    else:
        async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
            await admin.execute(
                sql.SQL("COMMENT ON ROLE {} IS {}").format(
                    sql.Identifier(desired.owner_role), sql.Literal(installation_marker("e" * 32))
                )
            )

    with pytest.raises(RestoreError) as refused:
        await run_restore(restores, desired, password, restore)

    assert refused.value.step == ("close" if wrong == "marker" else "verify")
    assert await place_count(desired, password) == 20
    assert await ledger_names(desired) == ["001_schema.sql", "002_change.sql"]


async def test_the_apps_sessions_are_ended_and_the_owner_is_closed_afterwards(plugin):
    desired, password, backup, restores, _ = plugin
    held = await connect_as(desired.app_role, password, desired.database_name)
    try:
        await run_restore(restores, desired, password, restore_of(backup))
        with pytest.raises(psycopg.OperationalError):
            await held.execute("SELECT 1")
    finally:
        await held.close()

    assert await owner_closed(desired)
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        assert await fetch_all(
            admin,
            "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
            "JOIN pg_roles u ON u.oid = m.member WHERE u.rolname = 'plugins_admin' "
            "AND m.grantor = m.member AND m.inherit_option",
        ) == []


async def test_plugins_admin_connects_only_to_postgres_and_pg_restore_logs_in_as_the_owner(
    plugin_databases, layout, client_root
):
    desired = plugin_databases()
    password = new_app_password()
    spy = ConnectionSpy()
    await DatabaseProvisioner(DatabaseConnector(admin_password())).ensure(
        "weather", desired, password, [migration("001_schema.sql", SCHEMA)]
    )
    runs = []

    async def spying(*argv, **options):
        import asyncio

        runs.append((argv, options["env"]))
        return await asyncio.create_subprocess_exec(*argv, **options)

    backups, restores, _ = backup_services(layout, client_root, connect=spy, create_process=spying)
    backup = await backups.backup(
        BackupRequest(plugin="weather", database=desired, upgrade_id=7, reason="pre_upgrade", version="0.6.0")
    )
    spy.connections.clear()

    await run_restore(restores, desired, password, restore_of(backup))

    assert {(connection["user"], connection["dbname"]) for connection in spy.connections} == {
        ("plugins_admin", "postgres"),
        (desired.owner_role, desired.database_name),
    }
    restore_runs = [environment for argv, environment in runs if "--single-transaction" in argv]
    assert [(environment["PGUSER"], environment["PGDATABASE"]) for environment in restore_runs] == [
        (desired.owner_role, desired.database_name)
    ]
    assert "-c role=none" in restore_runs[0]["PGOPTIONS"]
    assert not any("--role" in argument for argv, _ in runs for argument in argv)


async def test_a_template_mark_the_owner_set_does_not_stop_the_restore(plugin):
    desired, password, backup, restores, _ = plugin
    async with owner_session(desired) as owner:
        await owner.execute(sql.SQL("ALTER DATABASE {} IS_TEMPLATE true").format(sql.Identifier(desired.database_name)))

    await run_restore(restores, desired, password, restore_of(backup))

    assert await place_count(desired, password) == 30
