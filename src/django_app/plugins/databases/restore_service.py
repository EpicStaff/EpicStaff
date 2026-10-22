"""Restoring a plugin's database from a backup, during an upgrade that failed.

A SuperAdmin asks for it with the restore phrase; the node runs it with the database's owner
as the session user, after taking a backup of the database as it is (the way back). The
upgrade stays failed throughout. Once the restored ledger holds none of the new version's
migrations, the upgrade can be cancelled.
"""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from django.db import transaction
from rbac.validation.hard_delete import HardDeleteValidationService
from src.shared.models.plugin_nodes import RestoreReport

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_restore_finished, log_restore_requested
from plugins.databases.backup_records import (
    MAX_LISTED_BACKUPS,
    ListedBackup,
    not_restorable_reason,
    present_backups,
)
from plugins.exceptions import BackupNotFoundError, PluginNotFoundError, RestoreNotAllowedError
from plugins.lifecycle.lifecycle_locks import lock_existing_plugin
from plugins.lifecycle.open_upgrades import open_upgrade_of
from plugins.lifecycle.plugin_actions import (
    PluginActionFacts,
    PluginLifecycleAction,
    assert_plugin_action,
    restore_allowed,
)
from plugins.lifecycle.purge_phrases import assert_restore_phrase, restore_phrase
from plugins.models import (
    Plugin,
    PluginDatabase,
    PluginDatabaseBackup,
    PluginDatabaseRestore,
    PluginUpgrade,
    RestoreState,
)
from plugins.models.database import OPEN_RESTORE_STATES

RESTORED_MESSAGE = (
    "Database restored from {file_name}. Retry, upload a newer version, or cancel the upgrade."
)


@dataclass(frozen=True)
class BackupList:
    """A plugin's backups as its Runtime tab lists them, with the phrase a restore needs."""

    verification_phrase: str
    backups: list[ListedBackup]


class PluginRestoreService:
    def backups_of(self, identifier: str) -> BackupList:
        """The backups the plugin's node holds, newest first, at most `MAX_LISTED_BACKUPS`,
        each with whether it can be restored now; empty for a plugin without a database.

        Raises:
            PluginNotFoundError: No such plugin.
        """
        plugin = (
            Plugin.objects.select_related("current_package")
            .defer("current_package__icon_bytes")
            .filter(identifier=identifier)
            .first()
        )
        if plugin is None:
            raise PluginNotFoundError()
        database = PluginDatabase.objects.filter(plugin=plugin).first()
        listed = []
        if database is not None:
            facts = PluginActionFacts.of(plugin)
            allowed = restore_allowed(facts)
            backups = present_backups(database).select_related("upgrade")[:MAX_LISTED_BACKUPS]
            listed = [
                ListedBackup(
                    backup,
                    not_restorable_reason(backup, facts.open_upgrade, restore_allowed=allowed),
                )
                for backup in backups
            ]
        return BackupList(verification_phrase=restore_phrase(identifier), backups=listed)

    def request(
        self, identifier: str, backup_id: int, request_data, actor
    ) -> PluginDatabaseRestore:
        """Ask the node to restore `backup_id` into the plugin's database, in one transaction.

        Checked in this order before anything is written: the plugin exists, the backup is one
        of its database's that the node still holds (404), the plugin allows a restore now and
        this backup can be restored (409), the body's `verification_phrase` is exactly
        `restore-<identifier>` (400).

        Raises:
            PluginNotFoundError: No such plugin.
            BackupNotFoundError: No such present backup of the plugin's database.
            RestoreNotAllowedError: No failed migration of an open upgrade, a restore already
                runs, or the backup is another upgrade's or does not match its sha256.
            InvalidRestorePhraseError: The phrase is missing or different.
        """
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            upgrade = open_upgrade_of(plugin, lock=True)
            database = PluginDatabase.objects.filter(plugin=plugin).first()
            backup = (
                PluginDatabaseBackup.objects.filter(
                    pk=backup_id, plugin_database=database, deleted_at__isnull=True
                ).first()
                if database is not None
                else None
            )
            if backup is None:
                raise BackupNotFoundError()
            facts = PluginActionFacts.of(plugin, upgrade)
            assert_plugin_action(plugin, PluginLifecycleAction.RESTORE_BACKUP, facts)
            if not_restorable_reason(backup, upgrade, restore_allowed=restore_allowed(facts)):
                raise RestoreNotAllowedError()
            phrase = HardDeleteValidationService().extract_verification_phrase(request_data)
            assert_restore_phrase(phrase, restore_phrase(identifier))
            restore = PluginDatabaseRestore.objects.create(
                plugin_database=database,
                upgrade=upgrade,
                backup=backup,
                backup_file_name=backup.file_name,
                requested_by=actor,
            )
            ActivityRecorder().database_restore_requested(actor, identifier, backup.file_name)
            transaction.on_commit(
                partial(
                    log_restore_requested, actor, identifier=identifier, backup=backup.file_name
                )
            )
        return restore

    def apply_report(
        self, plugin: Plugin, upgrade: PluginUpgrade, report: RestoreReport, now: datetime
    ) -> None:
        """Apply the node's report about the upgrade's open restore; another restore's, or one
        about a restore that is over, changes nothing. Runs in the report's follow-up
        transaction, after the plugin and the upgrade were locked."""
        restore = (
            PluginDatabaseRestore.objects.select_for_update()
            .select_related("plugin_database")
            .filter(pk=report.restore_id, upgrade=upgrade, state__in=OPEN_RESTORE_STATES)
            .first()
        )
        if restore is None:
            return
        restore.step = report.step
        if report.state == RestoreState.RUNNING:
            restore.state = RestoreState.RUNNING
            restore.save(update_fields=["state", "step", "updated_at"])
            return
        restore.state = report.state
        restore.finished_at = now
        recorder = ActivityRecorder()
        if report.state == RestoreState.SUCCEEDED:
            restore.pre_restore_backup = (
                PluginDatabaseBackup.objects.filter(
                    plugin_database=restore.plugin_database, file_name=report.pre_restore_backup
                ).first()
                if report.pre_restore_backup
                else None
            )
            restore.last_error = None
            upgrade.last_error = RESTORED_MESSAGE.format(file_name=restore.backup_file_name)
            upgrade.save(update_fields=["last_error", "updated_at"])
            recorder.database_restored(
                plugin.identifier, restore.backup_file_name, report.pre_restore_backup
            )
        else:
            restore.last_error = report.last_error
            recorder.database_restore_failed(plugin.identifier, report.step, report.last_error)
        restore.save(
            update_fields=[
                "state",
                "step",
                "finished_at",
                "pre_restore_backup",
                "last_error",
                "updated_at",
            ]
        )
        transaction.on_commit(
            partial(
                log_restore_finished,
                identifier=plugin.identifier,
                restore_id=restore.pk,
                outcome=report.state,
                step=report.step,
            )
        )
