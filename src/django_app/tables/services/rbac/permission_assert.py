from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models.rbac_enums import Permission
from tables.services.rbac.permission_resolver import PermissionResolver

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
