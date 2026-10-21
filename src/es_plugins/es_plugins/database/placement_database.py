"""One placement's plugin database as this agent has seen it, and the lock that guards it.

The placement's controller provisions it, and the limits watchdog checks it, each while holding
`lock`: the watchdog skips a database whose lock is taken, so it never works on one that is
being provisioned. The report says what the last attempt came to.
"""

import asyncio
from datetime import datetime
from typing import Literal

from src.shared.models.plugin_nodes import (
    MAX_APPLIED_MIGRATIONS,
    MAX_LAST_ERROR_LENGTH,
    DatabaseReport,
    DesiredDatabase,
)

from es_plugins.database.migration_runner import MIGRATION_NAME_PATTERN
from es_plugins.database.provisioner import ProvisionedDatabase


class PlacementDatabase:
    def __init__(self, plugin: str, desired: DesiredDatabase):
        self.plugin = plugin
        self.desired = desired
        self.lock = asyncio.Lock()
        self.size_bytes: int | None = None
        self.limits_restored_at: datetime | None = None
        """When the watchdog last put the app role's limits back, in this agent's life."""

        self._state: Literal["provisioning", "ready", "failed"] = "provisioning"
        self._ledger: tuple[str, ...] = ()
        self._last_error: str | None = None

    @property
    def ready(self) -> bool:
        return self._state == "ready"

    def provisioning(self, desired: DesiredDatabase, error: str | None = None) -> None:
        """An attempt for `desired` starts, or (with `error`) has to be tried again later."""
        self.desired = desired
        self._state = "provisioning"
        self._last_error = error

    def provisioned(self, outcome: ProvisionedDatabase) -> None:
        self._state = "ready"
        self._ledger = outcome.ledger
        self.size_bytes = outcome.size_bytes
        self._last_error = None

    def failed(self, error: str) -> None:
        self._state = "failed"
        self._last_error = error

    def report(self) -> DatabaseReport:
        # The owner owns the ledger, so a migration may have written rows the report cannot
        # carry; only names a migration file can have are reported.
        ledger = [name for name in self._ledger if MIGRATION_NAME_PATTERN.fullmatch(name)]
        return DatabaseReport(
            installation_id=self.desired.installation_id,
            state=self._state,
            applied_migrations=ledger[:MAX_APPLIED_MIGRATIONS],
            size_bytes=self.size_bytes,
            last_error=self._last_error[:MAX_LAST_ERROR_LENGTH] if self._last_error else None,
            limits_restored_at=self.limits_restored_at,
        )
