from django.db import IntegrityError, transaction
from rbac.exceptions import OrganizationNotFoundError
from rbac.models import Organization

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_grant
from plugins.exceptions import (
    OrganizationInactiveError,
    PluginAlreadyGrantedError,
    PluginNotFoundError,
    PluginNotRunningError,
)
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.lifecycle_locks import lock_plugin
from plugins.models import GrantState, Plugin, PluginGrant, PluginServiceAccount, PluginState
from plugins.models.grant import GRANT_PER_ORGANIZATION_CONSTRAINT


class PluginGrantService:
    """Gives deployment-wide plugins to organizations."""

    def grant(self, identifier: str, organization_id: int, granted_by) -> PluginGrant:
        """Grant a running plugin to an active organization.

        A plugin without a backend is active at once. One with a backend also gets a service
        account in the organization; if its backend has an install hook, the grant starts
        `granting` with a pending install job, and the hook's result makes it `active` or
        `install_failed`. Everything is created in one transaction. A grant made while the
        plugin's upgrade is being prepared installs on the running version, and is upgraded
        with the others.

        Raises:
            PluginNotFoundError: No plugin with this identifier.
            OrganizationNotFoundError: No organization with this id.
            PluginNotRunningError: The plugin is not running.
            OrganizationInactiveError: The organization is deactivated.
            PluginAlreadyGrantedError: The organization already has a grant for the plugin.
        """
        try:
            with transaction.atomic():
                # Locked, so no grant is made while the plugin is being uninstalled or deleted.
                plugin = lock_plugin(identifier)
                if plugin is None:
                    raise PluginNotFoundError()
                organization = Organization.objects.filter(pk=organization_id).first()
                if organization is None:
                    raise OrganizationNotFoundError()
                if plugin.state != PluginState.RUNNING:
                    raise PluginNotRunningError()
                if not organization.is_active:
                    raise OrganizationInactiveError()
                package = plugin.current_package
                manifest = package.parsed_manifest
                has_backend = manifest.backend is not None
                runs_install_hook = has_backend and manifest.hooks.install
                grant = PluginGrant.objects.create(
                    plugin=plugin,
                    org=organization,
                    state=GrantState.GRANTING if runs_install_hook else GrantState.ACTIVE,
                    # With an install hook, set once the hook succeeds.
                    installed_version=None if runs_install_hook else package.version,
                    created_by=granted_by,
                )
                if has_backend:
                    PluginServiceAccount.objects.create(grant=grant)
                if runs_install_hook:
                    HookJobService().create_install_job(grant, package)
                ActivityRecorder().grant_created(granted_by, grant)
        except IntegrityError as error:
            # Checked by the constraint rather than beforehand, so two grants that race give
            # one grant and one conflict. Any other integrity error is a bug and surfaces.
            if _violated_constraint(error) != GRANT_PER_ORGANIZATION_CONSTRAINT:
                raise
            raise PluginAlreadyGrantedError() from None
        log_grant(granted_by, grant)
        return grant


def _violated_constraint(error: IntegrityError) -> str | None:
    diagnostics = getattr(error.__cause__, "diag", None)
    return getattr(diagnostics, "constraint_name", None)


def ensure_service_accounts(plugin: Plugin) -> int:
    """Give every grant of `plugin` that is not being purged a service account, if it has none.

    For a version that adds a backend: its grants were made without one. Runs with the
    plugin locked; returns how many were created.
    """
    missing = list(
        PluginGrant.objects.filter(plugin=plugin, service_account__isnull=True)
        .exclude(state=GrantState.PURGING)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    PluginServiceAccount.objects.bulk_create(
        PluginServiceAccount(grant_id=grant_id) for grant_id in missing
    )
    return len(missing)
