"""One placement's plugin database as this agent has seen it, and the lock that guards it.

The placement's controller provisions it, and the limits watchdog checks it, each while holding
`lock`: the watchdog skips a database whose lock is taken, so it never works on one that is
being provisioned. A removal holds the same lock while it drops the database, and retires it
first, so a watchdog pass that began before the placement went never checks it again. A backup
or a restore holds it too. The report says what the last attempt came to, and the ledger as the
node last read it: None until it has, in this agent's life.
"""

import asyncio
from datetime import datetime
from typing import Literal

from src.shared.models.plugin_nodes import (
    MAX_APPLIED_MIGRATIONS,
    MAX_LAST_ERROR_LENGTH,
    DatabaseReport,
    DesiredDatabase,
    LedgerEntry,
)

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
        self._ledger: tuple[LedgerEntry, ...] | None = None
        self._last_error: str | None = None
        self._retired = False

    @property
    def ready(self) -> bool:
        """Provisioned, and not being removed: what the limits watchdog checks."""
        return self._state == "ready" and not self._retired

    def retire(self) -> None:
        """The placement is being removed: nothing checks or provisions this database again."""
        self._retired = True

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

    def failed(self, error: str, *, ledger: tuple[LedgerEntry, ...] | None = None) -> None:
        """The attempt failed; `ledger` is what a failed migration run left, when it was read."""
        self._state = "failed"
        self._last_error = error
        if ledger is not None:
            self._ledger = ledger

    def report(self) -> DatabaseReport:
        # Every entry passed is_reportable_ledger_entry when it was read.
        ledger = None if self._ledger is None else list(self._ledger[:MAX_APPLIED_MIGRATIONS])
        return DatabaseReport(
            installation_id=self.desired.installation_id,
            state=self._state,
            applied_migrations=[entry.name for entry in ledger or ()],
            size_bytes=self.size_bytes,
            last_error=self._last_error[:MAX_LAST_ERROR_LENGTH] if self._last_error else None,
            limits_restored_at=self.limits_restored_at,
            ledger=ledger,
        )
