from django.db import IntegrityError, transaction
from rbac.exceptions import OrganizationNotFoundError
from rbac.models import Organization

from plugins.audit import log_grant
from plugins.exceptions import (
    OrganizationInactiveError,
    PluginAlreadyGrantedError,
    PluginNotFoundError,
    PluginNotRunningError,
)
from plugins.models import GrantState, Plugin, PluginGrant, PluginState
from plugins.models.grant import GRANT_PER_ORGANIZATION_CONSTRAINT


class PluginGrantService:
    """Gives deployment-wide plugins to organizations."""

    def grant(self, identifier: str, organization_id: int, granted_by) -> PluginGrant:
        """Grant a running plugin to an active organization.

        Plugins have no install hook yet, so the grant is active at once.

        Raises:
            PluginNotFoundError: No plugin with this identifier.
            OrganizationNotFoundError: No organization with this id.
            PluginNotRunningError: The plugin is not running.
            OrganizationInactiveError: The organization is deactivated.
            PluginAlreadyGrantedError: The organization already has a grant for the plugin.
        """
        plugin = Plugin.objects.filter(identifier=identifier).first()
        if plugin is None:
            raise PluginNotFoundError()
        organization = Organization.objects.filter(pk=organization_id).first()
        if organization is None:
            raise OrganizationNotFoundError()
        if plugin.state != PluginState.RUNNING:
            raise PluginNotRunningError()
        if not organization.is_active:
            raise OrganizationInactiveError()
        try:
            with transaction.atomic():
                grant = PluginGrant.objects.create(
                    plugin=plugin, org=organization, state=GrantState.ACTIVE, created_by=granted_by
                )
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
