"""Deleting a plugin for good: every organization's data, then everything of the plugin itself.

It starts when a SuperAdmin asks for it, or when an uninstalled plugin's grace period ends.
Every grant's data is deleted first (`GrantPurgeService`), each organization's removed hook
included. Once no grant, no waiting or running organization removed job and no owned row is
left, a plugin with a backend is handed to its node for removal: the node stops the process,
drops the plugin's database and roles, and deletes its code and files, then reports it done.
Only then are the plugin's rows deleted, and with them its port and Unix user id freed; after
commit its frontend and package files are deleted. A frontend-only plugin is finalized
without a node. Activity events stay. No backup is taken.
"""

import time
from dataclasses import dataclass
from functools import partial

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rbac.validation.hard_delete import HardDeleteValidationService
from src.shared.models.plugin_nodes import RemovalReport
from utils.logger import logger

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import (
    log_plugin_purge_started,
    log_plugin_purged,
    log_plugin_removal_failed,
    log_plugin_removal_requested,
)
from plugins.lifecycle.grant_purge_service import GrantPurgeService, PurgeReason
from plugins.lifecycle.lifecycle_locks import lock_existing_plugin, lock_grants_of, lock_plugin
from plugins.lifecycle.org_removed_hooks import OrgRemovedHookService
from plugins.lifecycle.plugin_actions import PluginLifecycleAction, assert_plugin_action
from plugins.lifecycle.purge_phrases import assert_purge_phrase, plugin_purge_phrase
from plugins.lifecycle.upgrade_service import PluginUpgradeService
from plugins.models import (
    GrantState,
    HookJobKind,
    HookJobState,
    PlacementRemovalState,
    Plugin,
    PluginDatabase,
    PluginGrant,
    PluginHookJob,
    PluginNode,
    PluginOwnedResource,
    PluginPlacement,
    PluginState,
)
from plugins.models.hook_job import OPEN_HOOK_JOB_STATES
from plugins.ownership.owned_resource_purger import OwnedResourcePurger
from plugins.packages.package_store import get_package_store
from plugins.packages.spa_publisher import SpaPublisher


class PluginPurgeService:
    def request(self, identifier: str, request_data, actor) -> Plugin:
        """Begin deleting a plugin now, as a SuperAdmin asked, in one transaction.

        Checked in this order before anything is written: the plugin exists (404), its state
        allows it (409), the body's `verification_phrase` is exactly `purge-<identifier>` (400).

        Raises:
            PluginNotFoundError: No such plugin.
            PluginNotPurgeableError: The plugin is uploaded, in maintenance or being deleted.
            InvalidPurgePhraseError: The phrase is missing or different.
        """
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            assert_plugin_action(plugin, PluginLifecycleAction.PURGE)
            phrase = HardDeleteValidationService().extract_verification_phrase(request_data)
            assert_purge_phrase(phrase, plugin_purge_phrase(identifier))
            self.begin(plugin, actor=actor, reason=PurgeReason.REQUESTED)
        return plugin

    def begin(self, plugin: Plugin, *, actor, reason: str) -> None:
        """Make `plugin` (locked by the caller) `purging`, and begin deleting every grant's data.

        An open upgrade is abandoned first (`PluginUpgradeService.abandon`). A plugin that was
        not uninstalled gets its uninstall dates set to now: nothing of it is kept. `actor`
        None is the platform.
        """
        PluginUpgradeService().abandon(plugin)
        now = timezone.now()
        if plugin.state != PluginState.UNINSTALLING:
            plugin.uninstall_requested_at = now
            plugin.purge_after = now
        plugin.state = PluginState.PURGING
        plugin.purge_started_at = now
        plugin.save(
            update_fields=[
                "state",
                "uninstall_requested_at",
                "purge_after",
                "purge_started_at",
                "updated_at",
            ]
        )
        grant_purge = GrantPurgeService()
        for grant in lock_grants_of(plugin):
            if grant.state != GrantState.PURGING:
                grant_purge.begin(grant, actor=actor, reason=PurgeReason.PLUGIN_DELETED)
        ActivityRecorder().plugin_purge_started(actor, plugin.identifier, reason)
        transaction.on_commit(
            partial(log_plugin_purge_started, actor, identifier=plugin.identifier, reason=reason)
        )

    def advance(self, plugin: Plugin, until: float) -> bool:
        """Move a purging plugin on, as far as it can go now; True once removal was requested
        or the plugin was finalized in this call.

        Deletes the owned rows whose grant is gone, organization by organization, until the
        `time.monotonic()` deadline. Once no grant is left, the platform skips the
        organization removed jobs that failed for good: the plugin's database is about to be
        dropped, and the data they would delete with it. Jobs still waiting or running are
        waited for. Once none is open and no owned row is left, removal is requested from the
        node, or a plugin without a placement is finalized at once.
        """
        purger = OwnedResourcePurger()
        organizations = (
            PluginOwnedResource.objects.filter(
                plugin_identifier=plugin.identifier, grant__isnull=True
            )
            .order_by("org_id")
            .values_list("org_id", flat=True)
            .distinct()
        )
        for organization_id in list(organizations):
            if time.monotonic() >= until:
                break
            purger.purge(
                organization_id=organization_id,
                plugin_identifier=plugin.identifier,
                grant=None,
                until=until,
            )
        with transaction.atomic():
            locked = lock_plugin(plugin.identifier, skip_locked=True)
            if locked is None or locked.state != PluginState.PURGING:
                return False
            if PluginGrant.objects.filter(plugin=locked).exists():
                return False
            now = timezone.now()
            OrgRemovedHookService().skip_failed(locked, now)
            if _open_org_removed_jobs(locked).exists():
                return False
            if PluginOwnedResource.objects.filter(plugin_identifier=locked.identifier).exists():
                return False
            placement = (
                PluginPlacement.objects.select_for_update(of=("self",))
                .select_related("node")
                .filter(plugin=locked)
                .first()
            )
            if placement is None:
                self.finalize(locked)
                return True
            if placement.removal_requested_at is not None:
                return False
            placement.removal_requested_at = now
            placement.save(update_fields=["removal_requested_at", "updated_at"])
            transaction.on_commit(
                partial(
                    log_plugin_removal_requested,
                    identifier=locked.identifier,
                    placement_id=placement.pk,
                    node=placement.node.name,
                )
            )
        return True

    def retry_removal(self, identifier: str, actor) -> Plugin:
        """Ask the node to try a failed removal again: a new generation of the removal.

        Raises:
            PluginNotFoundError: No such plugin.
            RemovalNotRetryableError: The node has not reported the removal failed.
        """
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            assert_plugin_action(plugin, PluginLifecycleAction.RETRY_REMOVAL)
            placement = PluginPlacement.objects.select_for_update().get(plugin=plugin)
            placement.restart_generation += 1
            placement.removal_state = None
            placement.removal_error = None
            placement.save(
                update_fields=["restart_generation", "removal_state", "removal_error", "updated_at"]
            )
            plugin.placement = placement
            ActivityRecorder().plugin_removal_retried(actor, identifier)
        return plugin

    def apply_removal_report(self, node: PluginNode, report: RemovalReport) -> None:
        """Apply what the node reports about removing one of its placements, in one
        transaction that locks the plugin, then the placement.

        Ignored unless the placement is the node's, its plugin is being deleted, its removal
        was requested and the report is about the current generation. `removed` finalizes the
        plugin; `failed` records the error, and the activity on the change into failed.
        """
        now = timezone.now()
        with transaction.atomic():
            plugin = (
                Plugin.objects.select_for_update(of=("self",), no_key=True)
                .select_related("current_package")
                .defer("current_package__icon_bytes")
                .filter(placement__pk=report.placement_id, placement__node=node)
                .first()
            )
            if plugin is None or plugin.state != PluginState.PURGING:
                return
            placement = PluginPlacement.objects.select_for_update().get(plugin=plugin)
            if (
                placement.removal_requested_at is None
                or report.generation != placement.restart_generation
            ):
                return
            if report.state == "removed":
                self.finalize(plugin)
                return
            if report.state == "failed":
                newly_failed = placement.removal_state != PlacementRemovalState.FAILED
                placement.removal_state = PlacementRemovalState.FAILED
                placement.removal_error = report.last_error
                if newly_failed:
                    ActivityRecorder().plugin_removal_failed(plugin.identifier, report.last_error)
                    transaction.on_commit(
                        partial(
                            log_plugin_removal_failed,
                            identifier=plugin.identifier,
                            placement_id=placement.pk,
                            error=report.last_error,
                        )
                    )
            else:
                # The error of a failed attempt stays until the removal is retried.
                placement.removal_state = PlacementRemovalState.REMOVING
            placement.removal_reported_at = now
            placement.save(
                update_fields=[
                    "removal_state",
                    "removal_error",
                    "removal_reported_at",
                    "updated_at",
                ]
            )

    def finalize(self, plugin: Plugin) -> None:
        """Delete the plugin's rows; the caller holds its lock, inside a transaction.

        The database record goes first (it protects the plugin row), then the placement, then
        the plugin with its packages, settings and hook jobs. After commit the plugin's
        published frontend and its package files are deleted; one that cannot be is logged
        with its key, to delete by hand.
        """
        identifier = plugin.identifier
        version = plugin.current_package.version if plugin.current_package is not None else None
        storage_keys = sorted(set(plugin.packages.values_list("storage_key", flat=True)))
        had_database = PluginDatabase.objects.filter(plugin=plugin).delete()[0] > 0
        PluginPlacement.objects.filter(plugin=plugin).delete()
        plugin.delete()
        ActivityRecorder().plugin_purged(identifier, version, had_database)
        transaction.on_commit(
            partial(log_plugin_purged, identifier=identifier, had_database=had_database)
        )

        def remove_published_files() -> None:
            try:
                SpaPublisher().remove_plugin(identifier)
            except Exception:  # after commit: nothing to undo, and the rest must still go
                logger.exception(
                    "Could not delete the published frontend of {identifier}; delete it by hand",
                    identifier=identifier,
                )
            store = get_package_store()
            for key in storage_keys:
                try:
                    store.delete(key)
                except Exception:  # one key must not keep the others
                    logger.exception(
                        "Could not delete {key} from the plugin package bucket; delete it by hand",
                        key=key,
                    )

        transaction.on_commit(remove_published_files, robust=True)


@dataclass(frozen=True)
class PurgeProgress:
    """How far a plugin's deletion has come.

    Attributes:
        node: `not_needed` without a backend; else the node's removal, `waiting` until it is
            requested and reported.
    """

    grants_left: int
    data_removals_waiting: int
    data_removals_failed: int
    node: str
    node_error: str | None


def purge_progress(plugin: Plugin) -> PurgeProgress | None:
    """The progress of a purging plugin, None for any other; two queries, the placement
    read from the plugin (select it with it)."""
    if plugin.state != PluginState.PURGING:
        return None
    jobs = PluginHookJob.objects.filter(plugin=plugin, kind=HookJobKind.ORG_REMOVED).aggregate(
        waiting=Count("pk", filter=Q(state__in=OPEN_HOOK_JOB_STATES)),
        failed=Count("pk", filter=Q(state=HookJobState.FAILED)),
    )
    try:
        placement = plugin.placement
    except PluginPlacement.DoesNotExist:
        node, node_error = "not_needed", None
    else:
        node = placement.removal_state or "waiting"
        node_error = placement.removal_error if node == PlacementRemovalState.FAILED else None
    return PurgeProgress(
        grants_left=PluginGrant.objects.filter(plugin=plugin).count(),
        data_removals_waiting=jobs["waiting"],
        data_removals_failed=jobs["failed"],
        node=node,
        node_error=node_error,
    )


def _open_org_removed_jobs(plugin: Plugin):
    return PluginHookJob.objects.filter(
        plugin=plugin, kind=HookJobKind.ORG_REMOVED, state__in=OPEN_HOOK_JOB_STATES
    )
