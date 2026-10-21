"""Every 60 s, check each ready plugin database from `postgres`, and restore or fail closed.

For each placement whose database is `ready` and whose lock is free (it is not being
provisioned), holding that lock:

1. **Permissions** (`ProvisioningAssertions.permission_problems`): a role attribute, a
   membership or a database privilege changed outside EpicStaff. The plugin's process is stopped
   and the placement reported `failed` until it is restarted; provisioning then checks again.
2. **The app role's limits** drifted (a plugin can rewrite its own role's settings): they are put
   back (`apply_app_limits`), `limits_restored_at` is set and `plugins.database.limits_restored`
   logged with the setting names, never their values.
3. **The owner can log in** (an agent died during a migration run, or someone changed it): it
   is set back to NOLOGIN and `plugins.database.owner_login_closed` logged.
4. **Size**: `pg_database_size` becomes `size_bytes`.

plugins_db not answering is logged once, until it answers again, and changes nothing. An SQL
error on one database is logged and that database is checked again at the next pass.
"""

import asyncio
import itertools
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

import psycopg
from loguru import logger

from es_plugins.database.app_role_limits import apply_app_limits
from es_plugins.database.connections import (
    DatabaseConnector,
    DatabaseUnreachableError,
    describe_error,
)
from es_plugins.database.migration_runner import close_owner_login
from es_plugins.database.placement_database import PlacementDatabase
from es_plugins.database.provisioner import database_size, log_database_failure
from es_plugins.database.provisioning_assertions import ProvisioningAssertions

CHECK_INTERVAL_SECONDS = 60.0
PERMISSIONS_CHANGED = "database permissions changed outside EpicStaff: "


class WatchedPlacement(Protocol):
    """A placement as the watchdog sees it (its controller)."""

    @property
    def database(self) -> PlacementDatabase | None: ...

    async def fail_database(self, error: str) -> None:
        """Stop the plugin's process and report the placement and its database failed."""


class DatabaseLimitsWatchdog:
    def __init__(
        self,
        connector: DatabaseConnector,
        placements: Callable[[], Iterable[WatchedPlacement]],
        on_change: Callable[[], None],
        *,
        assertions: ProvisioningAssertions | None = None,
        interval: float = CHECK_INTERVAL_SECONDS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._connector = connector
        self._placements = placements
        self._on_change = on_change
        self._assertions = assertions or ProvisioningAssertions()
        self._interval = interval
        self._clock = clock
        self._unreachable = False

    async def check_once(self) -> None:
        """One pass over every ready database, one admin session per database server."""
        watched = [placement for placement in self._placements() if _checkable(placement)]
        watched.sort(key=lambda placement: _server_key(placement.database))
        reachable = True
        for _, group in itertools.groupby(watched, key=lambda item: _server_key(item.database)):
            placements = list(group)
            try:
                async with self._connector.admin_session(
                    placements[0].database.desired.server
                ) as admin:
                    for placement in placements:
                        await self._check_placement(admin, placement)
            except DatabaseUnreachableError as error:
                reachable = False
                if not self._unreachable:
                    logger.warning("The limits watchdog cannot reach plugins_db: {}", error)
        if reachable and self._unreachable:
            logger.info("The limits watchdog reaches plugins_db again")
        self._unreachable = not reachable

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:
                # The watchdog must go on: one pass's unexpected error ends only that pass.
                logger.exception("The limits watchdog's pass failed")
            await asyncio.sleep(self._interval)

    async def _check_placement(
        self, admin: psycopg.AsyncConnection, placement: WatchedPlacement
    ) -> None:
        database = placement.database
        # Looked at again: the placement may have started provisioning since the pass began.
        if not _checkable(placement):
            return
        try:
            async with database.lock:
                violation = await self._check(admin, database)
        except psycopg.Error as error:
            if admin.broken:
                raise
            logger.warning(
                "The limits watchdog could not check the database of plugin {}: {}",
                database.plugin,
                describe_error(error),
            )
            return
        if violation is not None:
            log_database_failure(database.plugin, "assertion", violation)
            await placement.fail_database(violation)

    async def _check(
        self, admin: psycopg.AsyncConnection, database: PlacementDatabase
    ) -> str | None:
        """Check, restore and measure one database; return why it must fail, if it must."""
        desired = database.desired
        problems = await self._assertions.permission_problems(admin, desired)
        if problems:
            return PERMISSIONS_CHANGED + "; ".join(problems)
        drift = await self._assertions.drift(admin, desired)
        if drift.app_limits:
            await apply_app_limits(admin, desired)
            database.limits_restored_at = self._clock()
            logger.warning(
                "plugins.database.limits_restored plugin={} settings={}",
                database.plugin,
                ",".join(drift.app_limits),
            )
            self._on_change()
        if drift.owner_can_login:
            await close_owner_login(admin, desired.owner_role)
            # Something left the owner able to log in: an audit line, not an activity entry.
            logger.warning("plugins.database.owner_login_closed plugin={}", database.plugin)
        database.size_bytes = await database_size(admin, desired.database_name)
        return None


def _checkable(placement: WatchedPlacement) -> bool:
    database = placement.database
    return database is not None and database.ready and not database.lock.locked()


def _server_key(database: PlacementDatabase) -> tuple[str, int]:
    return database.desired.server.host, database.desired.server.port
