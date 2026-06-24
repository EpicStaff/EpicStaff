from tables.models.rbac_models import OrganizationUser
from tables.services.rbac.effective_permissions import EffectivePermissions
from tables.services.rbac.rbac_exceptions import OrgMembershipRequiredError


class PermissionResolver:
    """
    PermissionResolver — the single point that translates a (user, org)
    pair into an EffectivePermissions object.

    Bypass via `User.is_superadmin` happens here, so view layers
    never special-case superadmin.

    Cache seam: when a Redis cache lands later, it wraps the
    DB-fetch portion of resolve().
    """

    def resolve(self, user, org_id: int) -> EffectivePermissions:
        if getattr(user, "is_superadmin", False):
            return EffectivePermissions(is_superadmin=True, role=None, by_resource={})

        # NOTE: cache seam — when a Redis cache is added later, the two
        # queries below are what gets cached behind a key like
        # `rbac:perms:user:{user_id}:org:{org_id}`.
        membership = (
            OrganizationUser.objects.select_related("role", "org")
            .filter(user=user, org_id=org_id, org__is_active=True)
            .first()
        )
        if membership is None:
            raise OrgMembershipRequiredError()

        by_resource = {
            row.resource_type: row.permissions
            for row in membership.role.permissions_set.all()
        }
        return EffectivePermissions(
            is_superadmin=False,
            role=membership.role,
            by_resource=by_resource,
        )
