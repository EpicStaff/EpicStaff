"""End the database sessions a plugin's killed processes leave on plugins_db.

PostgreSQL runs a statement on after the client that sent it is gone: it notices only when it next
writes to that client, at `client_connection_check_interval` (set on plugins_db, but a session may
turn it off), or when the statement times out, and a plugin may raise its own session's timeout.
A plugin stopped for filling the disk could so go on filling it through its database, and the
floor would stop the other plugins one by one. So every time the node kills a plugin's processes,
it ends their sessions too:

- the app role's first, always: only the plugin's processes log in as it;
- then the owner role's, if the database's lock can be taken at once: a provisioning, restore,
  backup or limits check that holds the lock, or waits for it, is not waited for. Outside those
  the owner cannot log in at all, so a session of it is one a migration opened with a password of
  its own; inside a migration run or a restore the node's own owner session is running, and the
  run ends every owner session when it closes the owner's login.
"""

import asyncio

from loguru import logger

from es_plugins.database.connections import (
    DatabaseConnector,
    DatabaseProvisioningError,
    DatabaseUnreachableError,
    end_sessions,
)
from es_plugins.database.placement_database import PlacementDatabase

# Ending a session takes milliseconds; the rest bounds a slow connect, since the caller is
# stopping or restarting the plugin meanwhile. Within the supervisor's ON_KILLED_SECONDS.
SESSIONS_END_SECONDS = 1.0
ATTEMPT_SECONDS = 2.5


class PluginDatabaseSessions:
    def __init__(self, connector: DatabaseConnector):
        self._connector = connector

    async def end_after_kill(self, database: PlacementDatabase) -> None:
        """End the sessions the plugin's killed processes left; see the module docstring.

        A database being removed is left to its drop, which ends them itself. Never raises: a
        failure is logged, since the kill it follows has happened either way.
        """
        if database.retired:
            return
        desired = database.desired
        try:
            async with (
                asyncio.timeout(ATTEMPT_SECONDS),
                self._connector.admin_session(desired.server) as admin,
            ):
                remaining = await end_sessions(
                    admin, [desired.app_role], within_seconds=SESSIONS_END_SECONDS
                )
                if await _take_at_once(database.lock):
                    try:
                        remaining += await end_sessions(
                            admin, [desired.owner_role], within_seconds=SESSIONS_END_SECONDS
                        )
                    finally:
                        database.lock.release()
        except (DatabaseUnreachableError, DatabaseProvisioningError, TimeoutError) as error:
            logger.warning(
                "Could not end the database sessions of plugin {}: {}",
                database.plugin,
                str(error) or f"no answer within {ATTEMPT_SECONDS} s",
            )
            return
        if remaining:
            logger.warning(
                "{} database session(s) of plugin {} did not end", len(remaining), database.plugin
            )


async def _take_at_once(lock: asyncio.Lock) -> bool:
    # `acquire` returns without yielding only when the lock is free and no task is queued for it
    # (one woken by the last release included); a zero timeout turns any wait into a refusal.
    try:
        async with asyncio.timeout(0):
            await lock.acquire()
    except TimeoutError:
        return False
    return True
