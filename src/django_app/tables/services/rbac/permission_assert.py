from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models.rbac_enums import Permission
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.rbac.rbac_exceptions import PermissionEscalationError

_resolver = PermissionResolver()


def assert_org_permission(user, org_id: int, resource_type, action: Permission) -> None:
    """Assert `user` has `action` on `resource_type` within `org_id`.

    For non-ViewSet surfaces (plain APIViews) that have no DRF `action` and so
    cannot use HasOrgPermission. Resolve the active org first (e.g. via
    OrgContextService) and pass its id here. Superadmin bypasses (handled in
    PermissionResolver).

    Raises:
        OrgMembershipRequiredError (403): caller is not a member of the org.
        PermissionDenied (403): the caller's role lacks `action` on
            `resource_type`.
    """
    effective = _resolver.resolve(user=user, org_id=org_id)
    if not effective.can(resource_type, action):
        raise PermissionDenied("You do not have permission to perform this action.")


def assert_within_ceiling(effective, by_resource) -> None:
    """Assert every bit in `by_resource` is within `effective`'s own permissions.

    The escalation ceiling: you cannot grant authority you do not hold. Shared
    by the two places authority is handed out -- authoring a custom role (the
    bits written into it) and assigning any role to a member (the bits it
    grants) -- so the rule is stated once and the two cannot drift. Superadmin
    bypasses inside `EffectivePermissions.covers`.

    Raises:
        PermissionEscalationError (403): a requested bit exceeds `effective`.
    """
    if not effective.covers(by_resource):
        raise PermissionEscalationError()
