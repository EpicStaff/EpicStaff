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

# The manifest's `defaults` key for each built-in role a membership can hold. The bootstrap
# SuperAdmin's membership holds the built-in Superadmin role, which gets Org Admin's
# defaults while its holder is a SuperAdmin (`holds_plugin_role`): the flag alone never lets
# anyone use a plugin, and the membership alone does not once the flag is revoked.
BUILT_IN_ROLE_DEFAULT_KEYS = {
    BuiltInRole.SUPERADMIN: "org_admin",
    BuiltInRole.ORG_ADMIN: "org_admin",
    BuiltInRole.MEMBER: "member",
    BuiltInRole.VIEWER: "viewer",
}


def is_built_in_superadmin_role(role: Role) -> bool:
    return role.is_built_in and role.name == BuiltInRole.SUPERADMIN


def holds_plugin_role(user, role: Role) -> bool:
    """Whether `user`'s membership with `role` counts for plugin actions.

    Every role does, except the built-in Superadmin role, which counts only while its holder
    is a SuperAdmin: revoking the flag leaves that membership in place, and a demoted
    SuperAdmin must not keep Org Admin's plugin actions through it.
    """
    return not is_built_in_superadmin_role(role) or getattr(user, "is_superadmin", False) is True


def declared_actions(manifest: PluginManifest) -> list[str]:
    """Return the actions the plugin declares, in manifest order."""
    return [permission.action for permission in manifest.user_permissions]


def role_plugin_actions(
    role: Role, manifest: PluginManifest, stored_permissions: int = 0
) -> list[str]:
    """Return the actions a membership role has on a plugin, in manifest order.

    A built-in role gets the manifest's defaults, which no organization can change (the
    built-in Superadmin role gets Org Admin's). A
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


def stored_permissions_by_role(roles: Iterable[Role], grant_id: int) -> dict[int, int]:
    """Return the bitmask stored on one grant for each custom role of `roles`, by role id.

    Roles without a stored row are absent (no actions). At most one query; none when every
    role is built in.
    """
    custom_role_ids = {role.pk for role in roles if not role.is_built_in}
    if not custom_role_ids:
        return {}
    return dict(
        PluginRolePermission.objects.filter(
            grant_id=grant_id, role_id__in=custom_role_ids
        ).values_list("role_id", "permissions")
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
