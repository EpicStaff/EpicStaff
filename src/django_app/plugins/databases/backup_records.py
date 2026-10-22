"""The records of a plugin database's backups: what its node reports, which the node keeps,
and which a SuperAdmin may restore.

The node takes and holds the files; EpicStaff keeps a record of each and decides which the
node deletes (`backup_retention`), so a retry or a restore never loses the backup an open
upgrade needs, and no backup outlives the grace period or the three latest upgrades. A backup
is restorable only during the upgrade that took it (`not_restorable_reason`).

Adding a backup reason: `BackupReason` and the node contract's file-name pattern, its rule in
`backup_retention`, then the frontend's label for it.
"""

import operator
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from functools import partial, reduce

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from src.shared.models.plugin_nodes import MAX_BACKUPS_PER_PLACEMENT, BackupFileReport
from utils.logger import logger

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_backup_mismatch, log_backup_recorded
from plugins.configuration.grace_period import grace_period
from plugins.models import (
    BackupReason,
    PluginDatabase,
    PluginDatabaseBackup,
    PluginDatabaseRestore,
    PluginNode,
    PluginUpgrade,
)

# The latest pre-upgrade backups kept, within the grace period, besides what an open upgrade
# or restore needs.
BACKUPS_KEPT = 3
# The backups list shows at most this many, newest first.
MAX_LISTED_BACKUPS = 50

EARLIER_UPGRADE = "earlier_upgrade"
NOT_NOW = "not_now"
MISMATCH = "mismatch"


def present_backups(database: PluginDatabase) -> QuerySet[PluginDatabaseBackup]:
    """The database's backups its node still holds, newest first."""
    return database.backups.filter(deleted_at__isnull=True).order_by("-created_at", "-pk")


def restorable_backups(upgrade: PluginUpgrade) -> QuerySet[PluginDatabaseBackup]:
    """The present backups the upgrade took, apart from any with a sha256 mismatch."""
    return PluginDatabaseBackup.objects.filter(
        upgrade=upgrade, deleted_at__isnull=True, sha256_mismatch=False
    )


def not_restorable_reason(
    backup: PluginDatabaseBackup, open_upgrade: PluginUpgrade | None, *, restore_allowed: bool
) -> str | None:
    """Why `backup` cannot be restored now, or None when it can.

    `restore_allowed` says whether the plugin allows a restore at all now, apart from the
    backup (`plugin_actions`): its open upgrade failed while migrating or starting, and no
    restore is running.
    """
    if backup.sha256_mismatch:
        return MISMATCH
    if open_upgrade is None or backup.upgrade_id != open_upgrade.pk:
        return EARLIER_UPGRADE
    if not restore_allowed:
        return NOT_NOW
    return None


def backup_retention(
    backups: Iterable[PluginDatabaseBackup],
    *,
    open_upgrade_id: int | None,
    restoring_backup_id: int | None,
    now: datetime,
) -> list[str]:
    """The file names of `backups` (a database's present ones) its node should delete.

    Kept: every backup of the open upgrade (its pre-upgrade backup and each pre-restore
    backup), the backup an open restore reads, and the newest `BACKUPS_KEPT` pre-upgrade
    backups taken within the grace period. Every other is listed, oldest first, at most as
    many as a desired placement carries.
    """
    newest_first = sorted(backups, key=lambda backup: (backup.created_at, backup.pk), reverse=True)
    oldest_kept = now - grace_period()
    recent_pre_upgrade = [
        backup
        for backup in newest_first
        if backup.reason == BackupReason.PRE_UPGRADE and backup.created_at >= oldest_kept
    ][:BACKUPS_KEPT]
    kept = {backup.pk for backup in recent_pre_upgrade}
    kept |= {
        backup.pk
        for backup in newest_first
        if (open_upgrade_id is not None and backup.upgrade_id == open_upgrade_id)
        or backup.pk == restoring_backup_id
    }
    to_delete = [backup.file_name for backup in reversed(newest_first) if backup.pk not in kept]
    return to_delete[:MAX_BACKUPS_PER_PLACEMENT]


class BackupRecorder:
    """Records the backups a node reports for a plugin's database."""

    def record(
        self,
        database: PluginDatabase,
        report: BackupFileReport,
        *,
        identifier: str,
        node: PluginNode | None,
    ) -> PluginDatabaseBackup | None:
        """Record `report` once, and return its record; None for another installation's.

        For the node's `migrations` request, with the plugin and the upgrade locked. A new
        record is linked to its upgrade when that upgrade is the plugin's (`_create`); a
        known one, locked, listed again is present again. A file listed with another sha256
        than recorded is marked and never restored.
        """
        if report.installation_id != database.installation_id:
            logger.warning(
                "The plugin node reported a backup of another installation for {identifier}; "
                "ignored",
                identifier=identifier,
            )
            return None
        existing = self._existing(database, report.file_name)
        if existing is not None:
            self._update(existing, report, identifier)
            return existing
        upgrade = PluginUpgrade.objects.filter(
            pk=report.upgrade_id, plugin_id=database.plugin_id
        ).first()
        return self._create(database, report, upgrade, identifier=identifier, node=node)

    def apply_inventory(
        self,
        database: PluginDatabase,
        reports: Iterable[BackupFileReport],
        *,
        identifier: str,
        node: PluginNode | None,
    ) -> set[str]:
        """Record every backup a report lists; run in the report's transaction, with the
        database locked. Returns the file names recorded for this database.

        Two queries for the known ones and the upgrades the new ones name, whatever their
        number; a known row is locked only by the UPDATE that changes it, and a new one is
        created with its activity event.
        """
        reports = list(reports)
        ours = [report for report in reports if report.installation_id == database.installation_id]
        if len(ours) < len(reports):
            logger.warning(
                "The plugin node reported backups of another installation for {identifier}; "
                "ignored",
                identifier=identifier,
            )
        if not ours:
            return set()
        known = {
            backup.file_name: backup
            for backup in PluginDatabaseBackup.objects.filter(
                plugin_database=database, file_name__in=[report.file_name for report in ours]
            )
        }
        self._apply_known(
            [(known[report.file_name], report) for report in ours if report.file_name in known],
            identifier,
        )
        new = [report for report in ours if report.file_name not in known]
        # Linked only to an upgrade of this plugin.
        upgrades = (
            PluginUpgrade.objects.filter(plugin_id=database.plugin_id)
            .only("pk", "stage", "to_version")
            .in_bulk({report.upgrade_id for report in new})
            if new
            else {}
        )
        for report in new:
            self._create(
                database, report, upgrades.get(report.upgrade_id), identifier=identifier, node=node
            )
        return {report.file_name for report in ours}

    def _create(
        self,
        database: PluginDatabase,
        report: BackupFileReport,
        upgrade: PluginUpgrade | None,
        *,
        identifier: str,
        node: PluginNode | None,
    ) -> PluginDatabaseBackup:
        """Create the record, with its activity event and, while its upgrade is open, the
        version that upgrade is going to; a pre-restore backup is linked to the restore that
        named it before it was recorded."""
        try:
            with transaction.atomic():
                backup = PluginDatabaseBackup.objects.create(
                    plugin_database=database,
                    upgrade=upgrade,
                    node=node,
                    file_name=report.file_name,
                    reason=report.reason,
                    version=report.version,
                    taken_for_version=(
                        upgrade.to_version if upgrade is not None and upgrade.is_open else None
                    ),
                    size_bytes=report.size_bytes,
                    sha256=report.sha256,
                    created_at=report.created_at,
                )
        except IntegrityError:
            # The node's other request (the `migrations` request and a report carry the same
            # backup) inserted it first: this insert waited for that transaction on the
            # unique file name and failed once it committed. The row is there now.
            existing = self._existing(database, report.file_name)
            self._update(existing, report, identifier)
            return existing
        ActivityRecorder().database_backed_up(identifier, backup)
        transaction.on_commit(partial(log_backup_recorded, identifier, backup))
        if backup.reason == BackupReason.PRE_RESTORE:
            PluginDatabaseRestore.objects.filter(
                plugin_database=database,
                pre_restore_file_name=backup.file_name,
                pre_restore_backup__isnull=True,
            ).update(pre_restore_backup=backup)
        return backup

    @staticmethod
    def _existing(database: PluginDatabase, file_name: str) -> PluginDatabaseBackup | None:
        return (
            PluginDatabaseBackup.objects.select_for_update(no_key=True)
            .filter(plugin_database=database, file_name=file_name)
            .first()
        )

    @staticmethod
    def _update(backup: PluginDatabaseBackup, report: BackupFileReport, identifier: str) -> None:
        """Apply `report` to `backup`, which the caller locked."""
        changed = []
        if report.sha256 != backup.sha256 and not backup.sha256_mismatch:
            backup.sha256_mismatch = True
            changed.append("sha256_mismatch")
            log_backup_mismatch(identifier, backup.file_name)
        if backup.deleted_at is not None:
            backup.deleted_at = None
            changed.append("deleted_at")
        if changed:
            backup.save(update_fields=changed)

    @staticmethod
    def _apply_known(
        listed: list[tuple[PluginDatabaseBackup, BackupFileReport]], identifier: str
    ) -> None:
        """Apply what a report says about known backups (read without a lock) with UPDATEs
        that match only the rows that still need the change; none when nothing changes."""
        for backup, report in listed:
            if (
                report.sha256 != backup.sha256
                and not backup.sha256_mismatch
                and PluginDatabaseBackup.objects.filter(pk=backup.pk, sha256_mismatch=False).update(
                    sha256_mismatch=True
                )
            ):
                log_backup_mismatch(identifier, backup.file_name)
        listed_again = [backup.pk for backup, _ in listed if backup.deleted_at is not None]
        if listed_again:
            PluginDatabaseBackup.objects.filter(
                pk__in=listed_again, deleted_at__isnull=False
            ).update(deleted_at=None)


@dataclass(frozen=True)
class ListedBackup:
    """A backup as the backups list shows it."""

    backup: PluginDatabaseBackup
    not_restorable_reason: str | None

    @property
    def restorable(self) -> bool:
        return self.not_restorable_reason is None


def mark_unlisted_deleted(listed_by_database: dict[int, set[str]], now: datetime) -> int:
    """Mark the present backups of these databases that their node no longer lists as
    deleted, in one query; `listed_by_database` maps a database record's id to the file names
    its report listed."""
    if not listed_by_database:
        return 0
    still_listed = reduce(
        operator.or_,
        (
            Q(plugin_database_id=database_id, file_name__in=names)
            for database_id, names in listed_by_database.items()
        ),
    )
    return (
        PluginDatabaseBackup.objects.filter(
            plugin_database_id__in=list(listed_by_database), deleted_at__isnull=True
        )
        .exclude(still_listed)
        .update(deleted_at=now)
    )
