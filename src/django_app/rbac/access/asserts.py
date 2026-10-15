from rest_framework.exceptions import APIException, PermissionDenied

from rbac.access.resolver import PermissionResolver
from rbac.exceptions import OrgMembershipRequiredError, PermissionEscalationError
from rbac.models.enums import Permission

_resolver = PermissionResolver()


def assert_org_permission(user, org_id: int, resource_type, action: Permission) -> None:
    """Assert `user` has `action` on `resource_type` within `org_id`.

    For non-ViewSet surfaces (plain APIViews) that have no DRF `action` and so
    cannot use HasOrgPermission. Resolve the active org first (e.g. via
    OrgContextService) and pass its id here. Superadmin bypasses (handled in
    PermissionResolver). When the org comes from a row fetched by a raw id,
    use `assert_row_org_permission` instead.

    Raises:
        OrgMembershipRequiredError (403): caller is not a member of the org.
        PermissionDenied (403): the caller's role lacks `action` on
            `resource_type`.
    """
    effective = _resolver.resolve(user=user, org_id=org_id)
    if not effective.can(resource_type, action):
        raise PermissionDenied("You do not have permission to perform this action.")


def assert_row_org_permission(
    user, owner_org_id: int, resource_type, action: Permission, *, not_found: APIException
) -> None:
    """Assert `user` has `action` on `resource_type` over a row owned by `owner_org_id`.

    For APIViews that fetch a row by a raw id and only then learn its org. A caller
    outside that org gets `not_found` -- pass the exception the view raises for a
    missing id, so a foreign id is indistinguishable from a missing one. A member of
    the owning org whose role lacks `action` still gets 403: the row is in their own
    org, so its existence is no secret. Superadmin bypasses (handled in
    PermissionResolver).

    Raises:
        not_found: caller is not a member of `owner_org_id` (or the org is inactive).
        PermissionDenied (403): the caller's role lacks `action` on `resource_type`.
    """
    try:
        effective = _resolver.resolve(user=user, org_id=owner_org_id)
    except OrgMembershipRequiredError:
        raise not_found from None
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
