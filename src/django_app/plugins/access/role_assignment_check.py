from rbac.access.effective import EffectivePermissions
from rbac.exceptions import PermissionEscalationError
from rbac.models import Role

from plugins.access.plugin_permissions import role_actions_by_grant
from plugins.models import PluginGrant


class PluginRoleAssignmentCheck:
    """Refuses assigning a role whose plugin actions go beyond the assigner's own.

    Registered with rbac's role-assignment checks at app load. It runs whether or not the
    plugin platform is on: grants and stored plugin actions outlive a switch-off, so a role
    assigned while the platform is off keeps its plugin actions when it is turned back on.
    Every grant of the organization counts, not only the usable ones: actions stored on a
    suspended grant apply again when it resumes. A role's actions come from the one
    `plugin_permissions` resolution, so stored custom-role rows and built-in manifest
    defaults are judged alike. A SuperAdmin may assign anything. An organization without
    grants costs one query.
    """

    def assert_assignable(
        self, *, effective: EffectivePermissions, role: Role, org_id: int
    ) -> None:
        if effective.is_superadmin:
            return
        grants = list(PluginGrant.objects.filter(org_id=org_id).with_current_package())
        if not grants:
            return
        assigned = role_actions_by_grant(role, grants)
        own = role_actions_by_grant(effective.role, grants)
        if any(not set(assigned[grant.pk]) <= set(own[grant.pk]) for grant in grants):
            raise PermissionEscalationError()
