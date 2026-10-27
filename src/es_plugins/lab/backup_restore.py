"""The lab's backup and restore: run in the node's container as the agent's UID (10000), on stdin.

With the node's own services against the lab's plugins_db: provision a plugin database with rows
behind FORCE ROW LEVEL SECURITY, back it up as plugins_backup, change it the way a failed upgrade
would, restore the backup with the owner as the session user, and drop everything again. Prints
one JSON object for run.sh to check; never a password.
"""

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import stat
import uuid

from es_plugins.database.backup_service import BackupRequest, BackupService
from es_plugins.database.backup_store import BackupStore
from es_plugins.database.connections import DatabaseConnector
from es_plugins.database.drop_sequence import DatabaseDropper
from es_plugins.database.migration_runner import Migration
from es_plugins.database.postgres_client import PostgresClient
from es_plugins.database.provisioner import DatabaseProvisioner
from es_plugins.database.restore_service import RestoreService
from es_plugins.layout import NodeLayout
from es_plugins.node_disk import NodeDisk
from src.shared.models.plugin_nodes import (
    DesiredDatabase,
    DesiredDatabaseServer,
    DesiredRestore,
    database_names_for,
)

PLUGIN = "lab-backup"
SCHEMA = """
CREATE SCHEMA lab;
CREATE TABLE lab.places (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, org_id bigint NOT NULL, name text);
INSERT INTO lab.places (org_id, name) SELECT g % 3 + 1, 'place ' || g FROM generate_series(1, 300) g;
ALTER TABLE lab.places ENABLE ROW LEVEL SECURITY;
ALTER TABLE lab.places FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON lab.places TO ${app_role}
  USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);
-- What a migration may store for the owner: a library that does not exist refuses its every
-- login, unless the node overrides the setting and removes it before each owner login.
ALTER ROLE CURRENT_USER SET local_preload_libraries = 'missing_library';
DO $$ BEGIN
  EXECUTE format('ALTER ROLE CURRENT_USER IN DATABASE %I SET exit_on_error = on', current_database());
END $$;
"""
CHANGE = (
    "ALTER TABLE lab.places NO FORCE ROW LEVEL SECURITY; DELETE FROM lab.places WHERE id > 100; "
    "ALTER TABLE lab.places FORCE ROW LEVEL SECURITY;"
)


def migration(name: str, text: str) -> Migration:
    content = text.encode()
    return Migration(name=name, sha256=hashlib.sha256(content).hexdigest(), content=content)


async def place_count(desired: DesiredDatabase) -> int:
    """As plugins_backup on the plugin's database: BYPASSRLS sees every row."""
    import psycopg

    connection = await psycopg.AsyncConnection.connect(
        host=desired.server.host,
        port=desired.server.port,
        dbname=desired.database_name,
        user="plugins_backup",
        password=os.environ["PLUGINS_DB_BACKUP_PASSWORD"],
        options="-c default_transaction_read_only=on -c row_security=off",
    )
    try:
        cursor = await connection.execute("SELECT count(*) FROM lab.places")
        return (await cursor.fetchone())[0]
    finally:
        await connection.close()


async def owner_settings(connector: DatabaseConnector, desired: DesiredDatabase) -> list[str]:
    """Every setting stored for the owner, role-wide and in any database, sorted."""
    async with connector.admin_session(desired.server) as admin:
        cursor = await admin.execute(
            "SELECT unnest(setconfig) FROM pg_catalog.pg_db_role_setting "
            "WHERE setrole = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s)",
            (desired.owner_role,),
        )
        return sorted(row[0] for row in await cursor.fetchall())


async def main() -> dict:
    names = database_names_for(PLUGIN)
    desired = DesiredDatabase(
        server=DesiredDatabaseServer(name="plugins_db", host="plugins_db", port=5432),
        installation_id=uuid.uuid4().hex,
        database_name=names.database,
        owner_role=names.owner_role,
        app_role=names.app_role,
        job_role=names.job_role,
        connection_limit=3,
        statement_timeout_seconds=10,
    )
    layout = NodeLayout()
    connector = DatabaseConnector(os.environ["PLUGINS_DB_ADMIN_PASSWORD"])
    provisioner = DatabaseProvisioner(connector)
    store = BackupStore(layout)
    client = PostgresClient()
    backups = BackupService(
        connector,
        client,
        store,
        NodeDisk(layout.data_root),
        os.environ["PLUGINS_DB_BACKUP_PASSWORD"],
    )
    restores = RestoreService(connector, client, store, backups, provisioner)
    app_password = secrets.token_urlsafe(32)
    outcome: dict = {}
    try:
        await provisioner.ensure(
            PLUGIN, desired, app_password, [migration("001_schema.sql", SCHEMA)]
        )
        outcome["owner_settings_before"] = await owner_settings(connector, desired)
        outcome["rows_before"] = await place_count(desired)
        backup = await backups.backup(
            BackupRequest(
                plugin=PLUGIN, database=desired, upgrade_id=1, reason="pre_upgrade", version="0.1.0"
            )
        )
        directory = layout.plugin_backups(PLUGIN)
        outcome["backup"] = {
            "file": backup.file_name,
            "size_bytes": backup.metadata.size_bytes,
            "directory": oct(stat.S_IMODE(os.lstat(directory).st_mode)),
            "files": sorted(
                f"{name} {oct(stat.S_IMODE(os.lstat(directory / name).st_mode))}"
                for name in os.listdir(directory)
            ),
            "ledger": [entry.name for entry in backup.metadata.ledger or ()],
            "pg_dump": backup.metadata.pg_dump_version,
            "server": backup.metadata.server_version,
        }
        await provisioner.ensure(
            PLUGIN,
            desired,
            app_password,
            [migration("001_schema.sql", SCHEMA), migration("002_change.sql", CHANGE)],
        )
        outcome["rows_after_the_change"] = await place_count(desired)
        steps = []
        restored = await restores.restore(
            PLUGIN,
            desired,
            DesiredRestore(
                restore_id=1,
                upgrade_id=1,
                backup_file=backup.file_name,
                backup_sha256=backup.metadata.sha256,
            ),
            version="0.2.0",
            app_password=app_password,
            on_step=lambda step, pre_restore: steps.append(step),
        )
        outcome["restore"] = {
            "steps": steps,
            "pre_restore": restored.pre_restore.file_name,
            "ledger": [entry.name for entry in restored.provisioned.ledger],
        }
        outcome["rows_after_the_restore"] = await place_count(desired)
        outcome["owner_settings"] = await owner_settings(connector, desired)
    finally:
        await DatabaseDropper(connector).drop(desired)
        shutil.rmtree(layout.plugin_backups(PLUGIN), ignore_errors=True)
    return outcome


print(json.dumps(asyncio.run(main())))
