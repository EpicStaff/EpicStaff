"""Undo what a plugin's owner may set on its database that would stop a backup, restore or drop.

The owner of a database may mark it a template (`IS_TEMPLATE`, which `DROP DATABASE` refuses) and
cap its connections (`CONNECTION LIMIT 0`, which keeps the backup role out). Neither is anything a
plugin needs: the app role's own connection limit is the platform's. So before backing up,
restoring or dropping, the node puts them back, as the owner, from `postgres`.
"""

import psycopg
from psycopg import sql

_ATTRIBUTES = "SELECT datistemplate, datallowconn, datconnlimit FROM pg_catalog.pg_database WHERE datname = %s"
_DEFAULTS = (False, True, -1)


async def reset_database_attributes(
    admin: psycopg.AsyncConnection, database_name: str, owner_role: str
) -> bool:
    """Put the database's template mark, connection permission and limit back to the defaults.

    Runs on an admin session to `postgres`; returns whether anything was changed. A database that
    does not exist changes nothing.
    """
    cursor = await admin.execute(_ATTRIBUTES, (database_name,))
    found = await cursor.fetchone()
    if found is None or tuple(found) == _DEFAULTS:
        return False
    # As the owner: these are the owner's to change. SET LOCAL ends with the transaction.
    async with admin.transaction():
        await admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(owner_role)))
        await admin.execute(
            sql.SQL(
                "ALTER DATABASE {} IS_TEMPLATE false ALLOW_CONNECTIONS true CONNECTION LIMIT -1"
            ).format(sql.Identifier(database_name))
        )
    return True
