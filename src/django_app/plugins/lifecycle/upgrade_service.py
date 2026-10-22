"""Upgrading an installed plugin to a newer version: the stages, and every step between them.

A SuperAdmin starts an upgrade by approving a newer package (`start_locked`). A plugin with a
backend keeps running while its node prepares the target (`preparing`); the node then asks to
stop it (`advance` to `maintenance`), backs its database up, and asks to run the migrations
(`advance` to `migrations`, with the backup). Completion follows the node's report that the
target runs and is healthy (`follow_report`). A plugin without a backend before and after
completes at approval; one gaining a backend starts in `migrating`, with nothing to stop.

A failure leaves the upgrade in its stage. The SuperAdmin then retries it, approves a newer
version (which replaces the failed target in the same upgrade), cancels it while the database
holds none of the new version's migrations, or, after a failed migration or start, restores
the backup this upgrade took. EpicStaff never rolls back by itself.

Where a grant goes on every change is `settle_grant`'s. Lock order (`lifecycle_locks`): the
plugin, then the upgrade, then its restore, then the placement, then the grants.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from epicstaff_plugin.problems import Problem, format_loc
from pydantic import ValidationError
from src.shared.models.plugin_nodes import PlacementReport, UpgradeAdvance
from utils.logger import logger

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import (
    log_maintenance_started,
    log_migrations_started,
    log_setting_changes,
    log_upgrade_abandoned,
    log_upgrade_action,
    log_upgrade_done,
    log_upgrade_failed,
    log_upgrade_started,
)
from plugins.configuration.setting_values import apply_for_upgrade
from plugins.databases.backup_records import BackupRecorder
from plugins.databases.database_records import PluginDatabaseRecords
from plugins.databases.restore_service import PluginRestoreService
from plugins.exceptions import (
    AccessGrowthNotAcknowledgedError,
    InvalidUpgradeAdvanceError,
    ReviewOutdatedError,
    UntrustedNotAcknowledgedError,
    UpgradeNotCurrentError,
    UpgradeNotFoundError,
)
from plugins.lifecycle.grant_service import ensure_service_accounts
from plugins.lifecycle.grant_settling import SETTLED_FIELDS, settle_grant
from plugins.lifecycle.lifecycle_locks import lock_existing_plugin, lock_grants_of, lock_plugin
from plugins.lifecycle.open_upgrades import open_upgrade_of
from plugins.lifecycle.plugin_actions import (
    PluginActionFacts,
    PluginLifecycleAction,
    assert_plugin_action,
)
from plugins.lifecycle.upgrade_hooks import UpgradeHookService
from plugins.models import (
    BackupReason,
    GrantState,
    Plugin,
    PluginDatabase,
    PluginNode,
    PluginPackage,
    PluginPlacement,
    PluginState,
    PluginUpgrade,
    ReviewState,
    Trust,
    UpgradeStage,
)
from plugins.nodes.desired_state_builder import PLACED_PLUGIN_STATES
from plugins.nodes.placement_service import PlacementService
from plugins.packages.package_store import PluginPackageStore, get_package_store
from plugins.packages.spa_publisher import SpaPublisher
from plugins.packages.upgrade_review import access_growth
from plugins.packages.version_rules import (
    UpgradeCandidate,
    assert_upgrade_allowed,
    installed_version_with,
)

# The grants whose installed version an upgrade's completion brings up to date.
SETTLED_AT_COMPLETION = (GrantState.ACTIVE, GrantState.UPGRADING, GrantState.UPGRADE_FAILED)
ADVANCE_LOC = "advance"


def parse_upgrade_advance(raw: bytes) -> UpgradeAdvance:
    """Parse the node's `advance` body, ignoring fields this EpicStaff does not know.

    Raises:
        InvalidUpgradeAdvanceError: The body is not a valid request; problems located under
            `advance`.
    """
    try:
        return UpgradeAdvance.model_validate_json(raw, extra="ignore")
    except ValidationError as error:
        raise InvalidUpgradeAdvanceError(
            Problem(format_loc(ADVANCE_LOC, detail["loc"]), detail["msg"])
            for detail in error.errors(include_url=False)
        ) from None


@dataclass(frozen=True)
class ApprovalRequest:
    """What the SuperAdmin approves a package with."""

    untrusted_acknowledged: bool = False
    access_growth_acknowledged: bool = False
    reviewed_against_package_id: int | None = None
    settings: dict | None = None


class PluginUpgradeService:
    def __init__(
        self,
        publisher: SpaPublisher | None = None,
        store: PluginPackageStore | None = None,
        placements: PlacementService | None = None,
    ):
        self._publisher = publisher or SpaPublisher()
        self._store = store or get_package_store()
        self._placements = placements or PlacementService()

    # ---- start ----

    def start_locked(
        self,
        plugin: Plugin,
        package: PluginPackage,
        approved_by,
        request: ApprovalRequest,
        write_spa: Callable[[], None],
    ) -> PluginUpgrade:
        """Start the upgrade of an installed plugin to `package`, inside the approval's
        transaction, with the plugin and then the package locked.

        Every check runs before anything is written, in this order: the plugin's state, the
        version rules, the reviewed baseline, the untrusted and growth acknowledgements, the
        settings the new version needs. `write_spa` writes the new version's frontend; it is
        served only once the upgrade completes. An open, failed upgrade gets the package as
        its new target instead of a second upgrade.

        Raises:
            PluginNotUpgradableError: The plugin's state does not allow an upgrade now.
            PluginVersionNotNewerError: The package is not newer than the latest approved one.
            PluginUpgradeUnavailableError: The package cannot upgrade the installed plugin.
            ReviewOutdatedError: The approval did not name the baseline it was reviewed with.
            UntrustedNotAcknowledgedError: An untrusted package without the acknowledgement.
            AccessGrowthNotAcknowledgedError: The new version asks for new access without the
                acknowledgement.
            InvalidPluginSettingsError: A setting the new version needs is missing or invalid.
            NoPluginNodeError, PluginNodeFullError, NoPluginDatabaseServerError: A version
                that adds a backend or a database cannot be placed.
        """
        open_upgrade = open_upgrade_of(plugin, lock=True)
        assert_plugin_action(
            plugin, PluginLifecycleAction.UPGRADE, PluginActionFacts.of(plugin, open_upgrade)
        )
        manifest = package.parsed_manifest
        installed = installed_version_with(plugin, open_upgrade)
        assert_upgrade_allowed(UpgradeCandidate(manifest, package.migration_files), installed)
        baseline = installed.latest
        if request.reviewed_against_package_id != baseline.pk:
            raise ReviewOutdatedError()
        if package.trust == Trust.UNTRUSTED and not request.untrusted_acknowledged:
            raise UntrustedNotAcknowledgedError()
        growth = access_growth(baseline.parsed_manifest, manifest)
        if growth.requires_acknowledgement and not request.access_growth_acknowledged:
            raise AccessGrowthNotAcknowledgedError()
        changed_settings = apply_for_upgrade(plugin, manifest, request.settings or {}, approved_by)
        if changed_settings:
            transaction.on_commit(
                partial(log_setting_changes, approved_by, plugin.identifier, changed_settings)
            )
        write_spa()
        package.review_state = ReviewState.APPROVED
        package.approved_by = approved_by
        package.approved_at = timezone.now()
        package.save(update_fields=["review_state", "approved_by", "approved_at"])
        if manifest.backend is not None:
            self._placements.ensure_placement(plugin)
            ensure_service_accounts(plugin)
        if manifest.database is not None:
            PluginDatabaseRecords().ensure_for(plugin)
        if open_upgrade is not None:
            return self._replace_target(plugin, open_upgrade, package, approved_by, request)
        return self._open(plugin, package, approved_by, request)

    def _open(
        self, plugin: Plugin, package: PluginPackage, approved_by, request: ApprovalRequest
    ) -> PluginUpgrade:
        now = timezone.now()
        current = plugin.current_package
        had_backend = current.parsed_manifest.backend is not None
        adds_backend = not had_backend and package.parsed_manifest.backend is not None
        if had_backend:
            stage = UpgradeStage.PREPARING
        elif adds_backend:
            stage = UpgradeStage.MIGRATING
        else:
            stage = UpgradeStage.DONE
        database = PluginDatabase.objects.filter(plugin=plugin).only("ready_at").first()
        upgrade = PluginUpgrade.objects.create(
            plugin=plugin,
            from_package=current,
            to_package=package,
            from_version=current.version,
            to_version=package.version,
            stage=stage,
            backup_required=had_backend and database is not None and database.ready_at is not None,
            adds_backend=adds_backend,
            access_growth_acknowledged=request.access_growth_acknowledged,
            untrusted_acknowledged=request.untrusted_acknowledged,
            started_by=approved_by,
            started_at=now,
            # The node provisions the new backend's database at once: nothing to stop first.
            migrations_started_at=now if adds_backend else None,
            finished_at=now if stage == UpgradeStage.DONE else None,
        )
        self._record_started(plugin, upgrade, approved_by, replaced_version=None)
        if stage == UpgradeStage.DONE:
            self._complete(plugin, upgrade, now)
        return upgrade

    def _replace_target(
        self,
        plugin: Plugin,
        upgrade: PluginUpgrade,
        package: PluginPackage,
        approved_by,
        request: ApprovalRequest,
    ) -> PluginUpgrade:
        """Make `package` the target of the open, failed `upgrade`, keeping its backup.

        A plugin stopped for the upgrade stays stopped: from `migrating` it goes back to
        `maintenance`, so the node prepares the new target before it migrates again. An
        upgrade that adds a backend stops nothing and stays `migrating`.
        """
        previous = upgrade.to_package
        replaced_version = upgrade.to_version
        upgrade.to_package = package
        upgrade.to_version = package.version
        upgrade.failed_at = None
        upgrade.last_error = None
        upgrade.step = None
        upgrade.access_growth_acknowledged = request.access_growth_acknowledged
        upgrade.untrusted_acknowledged = request.untrusted_acknowledged
        if upgrade.stage == UpgradeStage.MIGRATING and not upgrade.adds_backend:
            upgrade.stage = UpgradeStage.MAINTENANCE
        upgrade.save()
        _bump_restart_generation(plugin)
        if previous is not None:
            self._delete_package(plugin.identifier, previous, discard_spa=True)
        self._record_started(plugin, upgrade, approved_by, replaced_version=replaced_version)
        return upgrade

    @staticmethod
    def _record_started(
        plugin: Plugin, upgrade: PluginUpgrade, approved_by, *, replaced_version: str | None
    ) -> None:
        ActivityRecorder().plugin_upgrade_started(
            approved_by,
            plugin.identifier,
            from_version=upgrade.from_version,
            to_version=upgrade.to_version,
            access_growth_acknowledged=upgrade.access_growth_acknowledged,
            untrusted_acknowledged=upgrade.untrusted_acknowledged,
            replaced_version=replaced_version,
        )
        transaction.on_commit(
            partial(
                log_upgrade_started,
                approved_by,
                identifier=plugin.identifier,
                from_version=upgrade.from_version,
                to_version=upgrade.to_version,
                replaced=replaced_version,
            )
        )

    # ---- the node's requests ----

    def advance(self, node: PluginNode, upgrade_id: int, request: UpgradeAdvance) -> None:
        """Take an upgrade of `node`'s to the stage its node asks for, in one transaction.

        Asking for the stage the upgrade is in already changes nothing. Otherwise the upgrade
        must be open, not failed, and in the stage before.

        Raises:
            UpgradeNotFoundError: No such upgrade on a placement of this node.
            UpgradeNotCurrentError: The upgrade is closed, failed, or cannot move to that
                stage from where it is.
            InvalidUpgradeAdvanceError: The backup the request carries is missing, not this
                upgrade's, or not the recorded one.
        """
        identifier = (
            PluginUpgrade.objects.filter(pk=upgrade_id, plugin__placement__node=node)
            .values_list("plugin__identifier", flat=True)
            .first()
        )
        if identifier is None:
            raise UpgradeNotFoundError()
        with transaction.atomic():
            plugin = lock_plugin(identifier)
            upgrade = open_upgrade_of(plugin, lock=True) if plugin is not None else None
            if upgrade is None or upgrade.pk != upgrade_id:
                raise UpgradeNotCurrentError()
            if request.to == "maintenance":
                self._advance_to_maintenance(plugin, upgrade, request)
            else:
                self._advance_to_migrations(plugin, upgrade, request, node)

    def _advance_to_maintenance(
        self, plugin: Plugin, upgrade: PluginUpgrade, request: UpgradeAdvance
    ) -> None:
        if upgrade.stage == UpgradeStage.MAINTENANCE:
            return
        if (
            upgrade.failed
            or upgrade.stage != UpgradeStage.PREPARING
            or plugin.state not in PLACED_PLUGIN_STATES
        ):
            raise UpgradeNotCurrentError()
        now = timezone.now()
        upgrade.stage = UpgradeStage.MAINTENANCE
        upgrade.maintenance_started_at = now
        upgrade.save(update_fields=["stage", "maintenance_started_at", "updated_at"])
        plugin.state = PluginState.MAINTENANCE
        plugin.save(update_fields=["state", "updated_at"])
        offline = 0
        for grant in lock_grants_of(plugin):
            if grant.state != GrantState.ACTIVE:
                continue
            settle_grant(grant)
            grant.save(update_fields=SETTLED_FIELDS)
            offline += 1
        ActivityRecorder().plugin_maintenance_started(
            plugin.identifier, upgrade.to_version, offline
        )
        transaction.on_commit(
            partial(
                log_maintenance_started,
                identifier=plugin.identifier,
                to_version=upgrade.to_version,
                grants=offline,
            )
        )
        self._set_maintenance_on_commit(plugin.identifier, True)

    def _advance_to_migrations(
        self, plugin: Plugin, upgrade: PluginUpgrade, request: UpgradeAdvance, node: PluginNode
    ) -> None:
        if upgrade.stage == UpgradeStage.MIGRATING:
            _assert_backup_is_the_recorded_one(upgrade, request)
            return
        if upgrade.failed or upgrade.stage != UpgradeStage.MAINTENANCE:
            raise UpgradeNotCurrentError()
        if upgrade.backup_required and upgrade.backup_id is None:
            database = PluginDatabase.objects.get(plugin=plugin)
            _assert_backup_belongs_to(upgrade, database, request)
            upgrade.backup = BackupRecorder().record(
                database, request.backup, identifier=plugin.identifier, node=node
            )
        else:
            _assert_backup_is_the_recorded_one(upgrade, request)
        now = timezone.now()
        upgrade.stage = UpgradeStage.MIGRATING
        upgrade.migrations_started_at = upgrade.migrations_started_at or now
        upgrade.save(update_fields=["stage", "backup", "migrations_started_at", "updated_at"])
        backup_name = upgrade.backup.file_name if upgrade.backup is not None else None
        transaction.on_commit(
            partial(
                log_migrations_started,
                identifier=plugin.identifier,
                to_version=upgrade.to_version,
                backup=backup_name,
            )
        )

    # ---- reports ----

    def follow_report(
        self, node: PluginNode, placement_id: int, observed: PlacementReport, now: datetime
    ) -> None:
        """Apply what a report means for the plugin, after the report's observations commit.

        One transaction that locks the plugin first, then its open upgrade and restore. A
        plugin another transaction holds is left alone: the node's next report brings the
        same observations. The plugin's state follows its process (`_follow_plugin_state`);
        the upgrade records the node's step and failures, fails when the target cannot
        start, and completes once the target runs healthy; a restore report goes to
        `PluginRestoreService`.
        """
        with transaction.atomic():
            plugin = (
                Plugin.objects.select_for_update(of=("self",), no_key=True, skip_locked=True)
                .select_related("current_package")
                .defer("current_package__icon_bytes")
                .filter(placement__pk=placement_id, placement__node=node)
                .first()
            )
            if plugin is None:
                return
            placement = PluginPlacement.objects.get(plugin=plugin)
            upgrade = open_upgrade_of(plugin, lock=True)
            stale = _is_stale(placement, observed)
            if not stale:
                _follow_plugin_state(plugin, observed, upgrade)
            if upgrade is None:
                return
            if observed.restore is not None:
                PluginRestoreService().apply_report(plugin, upgrade, observed.restore, now)
            if stale:
                return
            self._follow_upgrade_report(plugin, placement, upgrade, observed)
            if (
                upgrade.stage != UpgradeStage.MIGRATING
                or observed.observed_version != upgrade.to_version
            ):
                return
            if observed.observed_state == "failed":
                self._fail(plugin, upgrade, step="start", error=placement.last_error)
            elif observed.observed_state == "running" and observed.health == "ok":
                upgrade.stage = UpgradeStage.DONE
                upgrade.finished_at = now
                upgrade.save(update_fields=["stage", "finished_at", "updated_at"])
                self._complete(plugin, upgrade, now)

    def _follow_upgrade_report(
        self,
        plugin: Plugin,
        placement: PluginPlacement,
        upgrade: PluginUpgrade,
        observed: PlacementReport,
    ) -> None:
        report = observed.upgrade
        if (
            report is None
            or report.upgrade_id != upgrade.pk
            or report.generation != placement.restart_generation
            or report.stage != upgrade.stage
        ):
            return
        if report.state == "failed":
            self._fail(plugin, upgrade, step=report.step, error=report.last_error)
        elif upgrade.step != report.step:
            upgrade.step = report.step
            upgrade.save(update_fields=["step", "updated_at"])

    @staticmethod
    def _fail(plugin: Plugin, upgrade: PluginUpgrade, *, step: str, error: str | None) -> None:
        """Mark the upgrade failed at `step`, once per failure."""
        if upgrade.failed:
            return
        upgrade.failed_at = timezone.now()
        upgrade.step = step
        upgrade.last_error = error
        upgrade.save(update_fields=["failed_at", "step", "last_error", "updated_at"])
        ActivityRecorder().plugin_upgrade_failed(
            plugin.identifier,
            to_version=upgrade.to_version,
            stage=upgrade.stage,
            step=step,
            error=error,
        )
        transaction.on_commit(
            partial(
                log_upgrade_failed,
                identifier=plugin.identifier,
                to_version=upgrade.to_version,
                stage=upgrade.stage,
                step=step,
            )
        )

    def _complete(self, plugin: Plugin, upgrade: PluginUpgrade, now: datetime) -> None:
        """Make the upgrade's target the plugin's running package (the upgrade is `done`).

        Every grant that was active, upgrading or whose upgrade failed, and whose installed
        version is not the new one, goes where `settle_grant` says, and an upgrade hook that
        was failing gets every automatic retry again. Once this commits: the new frontend is
        served, the maintenance flag goes, the other frontend versions and every other
        package (but a pending one) are deleted. A failure there is logged; the frontend
        reconciler repairs the flag and `current`.
        """
        package = upgrade.to_package
        manifest = package.parsed_manifest
        plugin.current_package = package
        plugin.name = manifest.name
        plugin.description = manifest.description
        plugin.state = PluginState.RUNNING
        plugin.save(update_fields=["current_package", "name", "description", "state", "updated_at"])
        hooks = UpgradeHookService()
        for grant in lock_grants_of(plugin):
            if (
                grant.state not in SETTLED_AT_COMPLETION
                or grant.installed_version == package.version
            ):
                continue
            if settle_grant(grant) == GrantState.UPGRADING:
                hooks.restart_series(grant, now)
            grant.save(update_fields=SETTLED_FIELDS)
        if manifest.backend is not None:
            ensure_service_accounts(plugin)
        started = upgrade.maintenance_started_at
        maintenance_seconds = int((now - started).total_seconds()) if started else 0
        ActivityRecorder().plugin_upgraded(
            plugin.identifier,
            from_version=upgrade.from_version,
            to_version=upgrade.to_version,
            maintenance_seconds=maintenance_seconds,
        )
        transaction.on_commit(
            partial(
                log_upgrade_done,
                identifier=plugin.identifier,
                from_version=upgrade.from_version,
                to_version=upgrade.to_version,
                maintenance_seconds=maintenance_seconds,
            )
        )
        identifier = plugin.identifier
        version = package.version
        has_spa = manifest.spa is not None
        publisher = self._publisher

        def serve_new_version() -> None:
            if has_spa:
                publisher.switch_current(identifier, version)
            else:
                publisher.remove_current(identifier)
            publisher.set_maintenance(identifier, False)
            publisher.prune_versions(identifier, keep={version} if has_spa else set())

        transaction.on_commit(serve_new_version, robust=True)
        for old in plugin.packages.exclude(pk=package.pk).exclude(review_state=ReviewState.PENDING):
            self._delete_package(identifier, old, discard_spa=False)

    # ---- the SuperAdmin's actions ----

    def cancel(self, identifier: str, actor) -> Plugin:
        """Cancel the plugin's open upgrade, in one transaction.

        A plugin stopped for it starts again on its current version (`provisioning`, then
        `running` by the node's report); its upgrading grants go where `settle_grant` says.
        The target package is deleted, so its version can be uploaded again.

        Raises:
            PluginNotFoundError: No such plugin.
            UpgradeNotCancellableError: No open upgrade, it adds a backend, a restore runs, or
                the database holds a change of the new version.
        """
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            upgrade = open_upgrade_of(plugin, lock=True)
            assert_plugin_action(
                plugin,
                PluginLifecycleAction.CANCEL_UPGRADE,
                PluginActionFacts.of(plugin, upgrade),
            )
            stage = upgrade.stage
            upgrade.stage = UpgradeStage.CANCELLED
            upgrade.finished_at = timezone.now()
            upgrade.save(update_fields=["stage", "finished_at", "updated_at"])
            if plugin.state == PluginState.MAINTENANCE:
                plugin.state = PluginState.PROVISIONING
                plugin.save(update_fields=["state", "updated_at"])
                _bump_restart_generation(plugin)
            for grant in lock_grants_of(plugin):
                if grant.state == GrantState.UPGRADING:
                    settle_grant(grant)
                    grant.save(update_fields=SETTLED_FIELDS)
            if upgrade.to_package is not None:
                self._delete_package(plugin.identifier, upgrade.to_package, discard_spa=True)
            ActivityRecorder().plugin_upgrade_cancelled(
                actor, identifier, upgrade.to_version, stage
            )
            transaction.on_commit(
                partial(
                    log_upgrade_action,
                    "cancelled",
                    actor,
                    identifier=identifier,
                    to_version=upgrade.to_version,
                    stage=stage,
                )
            )
            self._set_maintenance_on_commit(identifier, False)
        return plugin

    def retry(self, identifier: str, actor) -> Plugin:
        """Have the node run the failed stage of the open upgrade again.

        Raises:
            PluginNotFoundError: No such plugin.
            UpgradeNotRetryableError: No open upgrade has failed, or a restore runs.
        """
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            upgrade = open_upgrade_of(plugin, lock=True)
            assert_plugin_action(
                plugin,
                PluginLifecycleAction.RETRY_UPGRADE,
                PluginActionFacts.of(plugin, upgrade),
            )
            upgrade.failed_at = None
            upgrade.last_error = None
            upgrade.step = None
            upgrade.save(update_fields=["failed_at", "last_error", "step", "updated_at"])
            _bump_restart_generation(plugin)
            ActivityRecorder().plugin_upgrade_retried(actor, identifier, upgrade.to_version)
            transaction.on_commit(
                partial(
                    log_upgrade_action,
                    "retried",
                    actor,
                    identifier=identifier,
                    to_version=upgrade.to_version,
                    stage=upgrade.stage,
                )
            )
        return plugin

    def abandon(self, plugin: Plugin) -> None:
        """Give up the plugin's open upgrade because the plugin is being deleted; the caller
        holds the plugin's lock.

        Once migrations started, the target becomes the current package: it is the version
        closest to what the database holds, so organization removed hooks run on it.
        """
        upgrade = open_upgrade_of(plugin, lock=True)
        if upgrade is None:
            return
        upgrade.stage = UpgradeStage.ABANDONED
        upgrade.finished_at = timezone.now()
        upgrade.save(update_fields=["stage", "finished_at", "updated_at"])
        migrations_started = upgrade.migrations_started_at is not None
        if migrations_started and upgrade.to_package is not None:
            plugin.current_package = upgrade.to_package
            plugin.save(update_fields=["current_package", "updated_at"])
        transaction.on_commit(
            partial(
                log_upgrade_abandoned,
                identifier=plugin.identifier,
                to_version=upgrade.to_version,
                migrations_started=migrations_started,
            )
        )
        self._set_maintenance_on_commit(plugin.identifier, False)

    # ---- helpers ----

    def _set_maintenance_on_commit(self, identifier: str, on: bool) -> None:
        publisher = self._publisher

        # A named function, not a `partial`: Django logs a failed robust callback by its
        # `__qualname__`, which a `partial` lacks.
        def set_maintenance_flag() -> None:
            publisher.set_maintenance(identifier, on)

        transaction.on_commit(set_maintenance_flag, robust=True)

    def _delete_package(
        self, identifier: str, package: PluginPackage, *, discard_spa: bool
    ) -> None:
        """Delete a package's row now and, once the transaction commits, its stored file and,
        with `discard_spa`, its unpublished frontend."""
        storage_key = package.storage_key
        version = package.version
        package.delete()
        store = self._store
        publisher = self._publisher

        def delete_package_files() -> None:
            if not PluginPackage.objects.filter(storage_key=storage_key).exists():
                store.delete(storage_key)
            if discard_spa:
                publisher.discard_version(identifier, version)

        transaction.on_commit(delete_package_files, robust=True)


def _bump_restart_generation(plugin: Plugin) -> None:
    PluginPlacement.objects.filter(plugin=plugin).update(
        restart_generation=F("restart_generation") + 1, updated_at=timezone.now()
    )


def _assert_backup_belongs_to(
    upgrade: PluginUpgrade, database: PluginDatabase, request: UpgradeAdvance
) -> None:
    backup = request.backup
    if backup is None:
        raise InvalidUpgradeAdvanceError(
            [Problem(f"{ADVANCE_LOC}.backup", "a backup of the database is required first")]
        )
    expected = {
        "installation_id": database.installation_id,
        "upgrade_id": upgrade.pk,
        "reason": BackupReason.PRE_UPGRADE,
        "version": upgrade.from_version,
    }
    problems = [
        Problem(f"{ADVANCE_LOC}.backup.{field}", f"must be {value}")
        for field, value in expected.items()
        if getattr(backup, field) != value
    ]
    if problems:
        raise InvalidUpgradeAdvanceError(problems)


def _assert_backup_is_the_recorded_one(upgrade: PluginUpgrade, request: UpgradeAdvance) -> None:
    backup = request.backup
    if backup is None:
        return
    recorded = upgrade.backup
    if recorded is None or (backup.file_name, backup.sha256) != (
        recorded.file_name,
        recorded.sha256,
    ):
        raise InvalidUpgradeAdvanceError(
            [Problem(f"{ADVANCE_LOC}.backup", "is not the backup recorded for this upgrade")]
        )


def _is_stale(placement: PluginPlacement, observed: PlacementReport) -> bool:
    """Whether the report is about a process from before the latest restart or settings change.

    Such a report, sent before the node picked up the new desired state, must not move the
    plugin: a `failed` from before a restart would undo the restart. A report without the
    applied values (no process started yet, a download that failed) is current.
    """
    return any(
        applied is not None and applied < current
        for applied, current in (
            (observed.applied_restart_generation, placement.restart_generation),
            (observed.applied_settings_revision, placement.settings_revision),
        )
    )


def _follow_plugin_state(
    plugin: Plugin, observed: PlacementReport, upgrade: PluginUpgrade | None
) -> None:
    """Move the plugin's state after its process, for its current package.

    A process of the current version reported running and healthy makes a `provisioning` or
    `failed` plugin `running`; one reported failed makes a `provisioning` or `running` plugin
    `failed`, but not while an upgrade is open: the upgrade records that failure. A plugin in
    maintenance never moves here; its upgrade's completion moves it.
    """
    package = plugin.current_package
    if package is None:
        return
    if (
        observed.observed_state == "running"
        and observed.health == "ok"
        and observed.observed_version == package.version
    ):
        _move(plugin, (PluginState.PROVISIONING, PluginState.FAILED), PluginState.RUNNING)
    elif observed.observed_state == "failed" and upgrade is None:
        _move(plugin, (PluginState.PROVISIONING, PluginState.RUNNING), PluginState.FAILED)


def _move(plugin: Plugin, from_states: tuple[str, ...], to_state: str) -> None:
    # The plugin is locked, so its state is current; a report that changes nothing (most of
    # them) issues no UPDATE.
    if plugin.state not in from_states:
        return
    plugin.state = to_state
    plugin.save(update_fields=["state", "updated_at"])
    logger.info(
        "Plugin {identifier} is now {state}, as its node reports",
        identifier=plugin.identifier,
        state=to_state,
    )
