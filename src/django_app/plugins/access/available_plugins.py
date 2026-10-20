from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models.functions import Lower
from epicstaff_plugin.contracts.manifest import READ_ACTION
from rbac.models import OrganizationUser

from plugins.access.plugin_permissions import role_plugin_actions
from plugins.models import GrantState, Plugin, PluginGrant, PluginState


@dataclass(frozen=True)
class AvailablePlugin:
    """A plugin a person may open in an organization, with their actions on it."""

    plugin: Plugin
    permissions: list[str]


def plugins_available_to(user, org_id: int) -> list[AvailablePlugin]:
    """Return the plugins `user` may open in organization `org_id`, sorted by name.

    A plugin counts when it is running, its grant to the organization is active, and the
    person's membership role has View on it. Rights come from the membership only: a
    SuperAdmin who is not a member, or a caller that is not a user (the system API key),
    gets none. Two queries, whatever the number of plugins.
    """
    if not isinstance(user, get_user_model()):
        return []
    membership = (
        OrganizationUser.objects.select_related("role")
        .filter(user=user, org_id=org_id, org__is_active=True)
        .first()
    )
    if membership is None:
        return []
    grants = (
        PluginGrant.objects.filter(
            org_id=org_id,
            state=GrantState.ACTIVE,
            plugin__state=PluginState.RUNNING,
            plugin__current_package__isnull=False,
        )
        .select_related("plugin__current_package")
        .defer("plugin__current_package__icon_bytes")
        .order_by(Lower("plugin__name"), "plugin__identifier")
    )
    available = []
    for grant in grants:
        manifest = grant.plugin.current_package.parsed_manifest
        actions = role_plugin_actions(membership.role, manifest)
        if READ_ACTION in actions:
            available.append(AvailablePlugin(plugin=grant.plugin, permissions=actions))
    return available
