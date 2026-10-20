from epicstaff_plugin.contracts.manifest import PluginManifest
from rbac.models import Role
from rbac.models.enums import BuiltInRole

# The manifest's `defaults` key for each built-in role a membership can hold.
BUILT_IN_ROLE_DEFAULT_KEYS = {
    BuiltInRole.ORG_ADMIN: "org_admin",
    BuiltInRole.MEMBER: "member",
    BuiltInRole.VIEWER: "viewer",
}


def role_plugin_actions(role: Role, manifest: PluginManifest) -> list[str]:
    """Return the actions a membership role has on a plugin.

    A built-in role gets the manifest's defaults, which no organization can change. Any
    other role gets nothing until custom roles can be given plugin permissions.
    """
    if not role.is_built_in or role.org_id is not None:
        return []
    default_key = BUILT_IN_ROLE_DEFAULT_KEYS.get(role.name)
    if default_key is None:
        return []
    return manifest.user_permission_defaults(default_key)
