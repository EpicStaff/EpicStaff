"""Deleting a grant's data: everything the plugin made in the organization, then the grant.

It starts when a SuperAdmin asks for it, when a suspended grant's grace period ends, or when
the plugin itself is deleted. The grant then takes the suspension's steps first, unless it is
suspended already, and becomes `purging`. Two tracks run side by side from there: the
scheduled maintenance deletes the rows the plugin owns in the organization
(`OwnedResourcePurger`), and the plugin's organization removed hook deletes its own data. The
grant row goes once both are done; its service account, keys and role actions go with it.
Runs stay refused while anything it owns is left (`purging` is not `active`).
"""

from enum import StrEnum

from django.db import transaction
from django.utils import timezone
from rbac.validation.hard_delete import HardDeleteValidationService

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_grant_purge_started, log_grant_purged
from plugins.lifecycle.grant_actions import GrantAction, assert_grant_action
from plugins.lifecycle.lifecycle_locks import lock_grant, lock_plugin
from plugins.lifecycle.org_removed_hooks import (
    SETTLED_ORG_REMOVED_STATES,
    OrgRemovedHookService,
    latest_org_removed_job,
)
from plugins.lifecycle.purge_phrases import assert_purge_phrase, grant_purge_phrase
from plugins.lifecycle.suspension_service import stop_sessions_on_commit, withdraw_access
from plugins.models import GrantState, HookJobState, PluginGrant, PluginState
from plugins.ownership.existing_owned import owned_resource_counts_by_grant
from plugins.ownership.owned_resource_purger import (
    OwnedResourcePurger,
    PurgePassResult,
    purge_targets,
)

DELETED_BEFORE_HOOK_FINISHED = "Deleted before the hook finished."


class PurgeReason(StrEnum):
    """Why deleting a grant's or a plugin's data began."""

    REQUESTED = "requested"
    GRACE_PERIOD_OVER = "grace_period_over"
    PLUGIN_DELETED = "plugin_deleted"


class GrantPurgeService:
    def request(self, identifier: str, grant_id: int, request_data, actor) -> PluginGrant:
        """Begin deleting a grant's data now, as a SuperAdmin asked, in one transaction.

        Checked in this order before anything is written: the grant exists (404), the grant
        and its plugin allow it (409), the body's `verification_phrase` is exactly
        `purge-<identifier>-<organization name>` (400).

        Raises:
            GrantNotFoundError: No such grant of this plugin.
            GrantNotPurgeableError: The grant, or its plugin, is already being deleted.
            InvalidPurgePhraseError: The phrase is missing or different.
        """
        with transaction.atomic():
            grant = lock_grant(identifier, grant_id)
            assert_grant_action(grant, GrantAction.PURGE)
            phrase = HardDeleteValidationService().extract_verification_phrase(request_data)
            assert_purge_phrase(phrase, grant_purge_phrase(identifier, grant.org.name))
            self.begin(grant, actor=actor, reason=PurgeReason.REQUESTED)
        return grant

    def begin(self, grant: PluginGrant, *, actor, reason: str) -> None:
        """Make `grant` `purging`; the caller holds the plugin's lock, then the grant's.

        A grant that is not suspended yet first loses what a suspension takes away (its open
        hook jobs fail, its keys are revoked, and its organization's sessions that use what
        the plugin owns stop after commit), with no `grant_suspended` event. Then the
        plugin is asked to delete its own data for the organization, when it has the hook.
        `actor` None is the platform.
        """
        now = timezone.now()
        previous_state = grant.state
        if grant.state != GrantState.SUSPENDED:
            withdraw_access(grant, now, hook_error=DELETED_BEFORE_HOOK_FINISHED)
            stop_sessions_on_commit(grant)
        grant.state = GrantState.PURGING
        grant.purge_started_at = now
        grant.save(
            update_fields=[
                "state",
                "suspended_at",
                "last_hook_error",
                "purge_started_at",
                "updated_at",
            ]
        )
        OrgRemovedHookService().ensure_job(
            grant.plugin,
            organization_id=grant.org_id,
            organization_name=grant.org.name,
            grant=grant,
        )
        owned_resources = owned_resource_counts_by_grant([grant.pk]).get(grant.pk, 0)
        ActivityRecorder().grant_purge_started(
            actor,
            grant,
            reason=reason,
            previous_state=previous_state,
            owned_resources=owned_resources,
        )
        identifier = grant.plugin.identifier
        grant_id = grant.pk
        organization_id = grant.org_id

        def log_started() -> None:
            log_grant_purge_started(
                actor,
                identifier=identifier,
                grant_id=grant_id,
                org_id=organization_id,
                reason=reason,
                previous_state=previous_state,
            )

        transaction.on_commit(log_started)

    def advance(self, grant: PluginGrant, until: float) -> PurgePassResult:
        """Delete what the plugin owns under a purging grant, until the `time.monotonic()`
        deadline.

        The grant keeps the first error of a pass that failed. A pass that held back rows
        which failed within the hour keeps the error the grant has, so it does not vanish
        until a pass gets through them; only a pass with no failure that held back nothing
        clears it.
        """
        result = OwnedResourcePurger().purge(
            organization_id=grant.org_id,
            plugin_identifier=grant.plugin.identifier,
            grant=grant,
            until=until,
        )
        if result.failed:
            last_error = result.first_error
        elif result.held_back:
            return result
        else:
            last_error = None
        PluginGrant.objects.filter(pk=grant.pk, state=GrantState.PURGING).exclude(
            last_purge_error=last_error
        ).update(last_purge_error=last_error, updated_at=timezone.now())
        return result

    def finish_if_done(self, grant: PluginGrant) -> bool:
        """Delete a purging grant whose two tracks are both done; True when it did.

        Done means no ownership row of it (nor of its organization and plugin without a
        grant) is left, and the organization's latest organization removed job, if any,
        succeeded or was skipped. While the plugin itself is being deleted, a job that failed
        for good counts as done too: the plugin's database goes next, and the job is skipped
        once no grant is left. Locks the plugin, then the grant, each skipped when another
        process holds it.
        """
        identifier = grant.plugin.identifier
        with transaction.atomic():
            plugin = lock_plugin(identifier, skip_locked=True)
            if plugin is None:
                return False
            locked = (
                PluginGrant.objects.select_for_update(skip_locked=True)
                .filter(pk=grant.pk, plugin=plugin, state=GrantState.PURGING)
                .first()
            )
            if locked is None:
                return False
            if purge_targets(locked.org_id, identifier, locked).exists():
                return False
            job = latest_org_removed_job(plugin.pk, locked.org_id)
            settled = SETTLED_ORG_REMOVED_STATES + (
                (HookJobState.FAILED,) if plugin.state == PluginState.PURGING else ()
            )
            if job is not None and job.state not in settled:
                return False
            grant_id = locked.pk
            organization_id = locked.org_id
            locked.delete()
            ActivityRecorder().grant_purged(identifier, organization_id)
            transaction.on_commit(
                lambda: log_grant_purged(
                    identifier=identifier, grant_id=grant_id, org_id=organization_id
                )
            )
        return True
