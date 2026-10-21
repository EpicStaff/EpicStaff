"""A membership role's actions on a plugin: the one resolution every plugin check uses.

The left bar (`available`) and the Roles matrix ceiling both ask here, so a role that can
open a plugin is exactly a role the matrix shows with View.
"""

from collections.abc import Iterable

from epicstaff_plugin.contracts.manifest import PluginManifest
from rbac.access.bitmask import bitmask_to_actions
from rbac.models import Role
from rbac.models.enums import BuiltInRole

from plugins.models import PluginGrant, PluginRolePermission

# The manifest's `defaults` key for each built-in role a membership can hold.
BUILT_IN_ROLE_DEFAULT_KEYS = {
    BuiltInRole.ORG_ADMIN: "org_admin",
    BuiltInRole.MEMBER: "member",
    BuiltInRole.VIEWER: "viewer",
}


def declared_actions(manifest: PluginManifest) -> list[str]:
    """Return the actions the plugin declares, in manifest order."""
    return [permission.action for permission in manifest.user_permissions]


def role_plugin_actions(
    role: Role, manifest: PluginManifest, stored_permissions: int = 0
) -> list[str]:
    """Return the actions a membership role has on a plugin, in manifest order.

    A built-in role gets the manifest's defaults, which no organization can change. A
    custom role gets the actions stored for it on the plugin's grant to its organization
    (`stored_permissions`, the bitmask `stored_permissions_by_grant` returns), limited to
    the actions the plugin declares.
    """
    if role.is_built_in:
        default_key = BUILT_IN_ROLE_DEFAULT_KEYS.get(role.name)
        if role.org_id is not None or default_key is None:
            return []
        return manifest.user_permission_defaults(default_key)
    return bitmask_to_actions(stored_permissions, applicable=declared_actions(manifest))


def stored_permissions_by_grant(role: Role, grant_ids: Iterable[int]) -> dict[int, int]:
    """Return the bitmask stored for a custom role on each of `grant_ids`, by grant id.

    Grants without a stored row are absent (no actions). Built-in roles are never stored,
    so no query runs for them.
    """
    grant_ids = list(grant_ids)
    if role.is_built_in or not grant_ids:
        return {}
    return dict(
        PluginRolePermission.objects.filter(role=role, grant_id__in=grant_ids).values_list(
            "grant_id", "permissions"
        )
    )


def role_actions_by_grant(role: Role, grants: Iterable[PluginGrant]) -> dict[int, list[str]]:
    """Return `role`'s actions on each grant's plugin, by grant id, in one query at most.

    The one resolution every caller uses: the left bar, the Roles matrix and role
    assignment. Each grant must come with its plugin's current package.
    """
    grants = list(grants)
    stored = stored_permissions_by_grant(role, (grant.pk for grant in grants))
    return {
        grant.pk: role_plugin_actions(
            role, grant.plugin.current_package.parsed_manifest, stored.get(grant.pk, 0)
        )
        for grant in grants
    }
