"""Undo what a plugin's roles may set that would stop a backup, restore or drop.

The owner of a database may mark it a template (`IS_TEMPLATE`, which `DROP DATABASE` refuses) and
cap its connections (`CONNECTION LIMIT 0`, which keeps the backup role out). Neither is anything a
plugin needs: the app role's own connection limit is the platform's. So before backing up,
restoring or dropping, the node puts them back, as the owner, from `postgres`.

A database closed to logins (`ALLOW_CONNECTIONS false`) is left closed here: the database may
still have the default ACL, in which PUBLIC may connect (a run that stopped between
`provisioner.create_closed_database` and `provisioner.grant_connect`), and opening it on its own
would let every role on the server log in. Only `grant_connect` opens a database, in the
transaction that revokes CONNECT from PUBLIC: the backup and the restore run it next, and a
database about to be dropped need not be open.

Any role may store settings for itself (`ALTER ROLE CURRENT_USER SET …`, also `IN DATABASE …`),
which apply at its every login: `reset_role_settings` removes them for the app role and the owner,
whose settings are the platform's.
"""

import psycopg
from psycopg import sql

_ROLE_SETTING_DATABASES = (
    "SELECT d.datname FROM pg_catalog.pg_db_role_setting s "
    "JOIN pg_catalog.pg_database d ON d.oid = s.setdatabase "
    "WHERE s.setrole = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s)"
)
_ATTRIBUTES = "SELECT datistemplate, datconnlimit FROM pg_catalog.pg_database WHERE datname = %s"
_DEFAULTS = (False, -1)


async def reset_database_attributes(
    admin: psycopg.AsyncConnection, database_name: str, owner_role: str
) -> bool:
    """Put the database's template mark and connection limit back to the defaults.

    Never opens a database closed to logins; see the module. Runs on an admin session to
    `postgres`; returns whether anything was changed. A database that does not exist changes
    nothing.
    """
    cursor = await admin.execute(_ATTRIBUTES, (database_name,))
    found = await cursor.fetchone()
    if found is None or tuple(found) == _DEFAULTS:
        return False
    # As the owner: these are the owner's to change. SET LOCAL ends with the transaction.
    async with admin.transaction():
        await admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(owner_role)))
        await admin.execute(
            sql.SQL("ALTER DATABASE {} IS_TEMPLATE false CONNECTION LIMIT -1").format(
                sql.Identifier(database_name)
            )
        )
    return True


async def reset_role_settings(admin: psycopg.AsyncConnection, role: str) -> None:
    """Remove every setting stored for `role`, role-wide and in each database, in one transaction.

    Runs on an admin session to `postgres`, which administers the plugin's roles.
    """
    identifier = sql.Identifier(role)
    async with admin.transaction():
        await admin.execute(sql.SQL("ALTER ROLE {} RESET ALL").format(identifier))
        cursor = await admin.execute(_ROLE_SETTING_DATABASES, (role,))
        for (database_name,) in await cursor.fetchall():
            await admin.execute(
                sql.SQL("ALTER ROLE {} IN DATABASE {} RESET ALL").format(
                    identifier, sql.Identifier(database_name)
                )
            )
