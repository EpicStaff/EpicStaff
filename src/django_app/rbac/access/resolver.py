from rbac.access.effective import EffectivePermissions
from rbac.access.principals import is_pinned_org_principal
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models import OrganizationUser


class PermissionResolver:
    """
    PermissionResolver — the single point that translates a (user, org)
    pair into an EffectivePermissions object.

    Bypass via `User.is_superadmin` happens here, so view layers
    never special-case superadmin.

    A `PinnedOrgPrincipal` resolves its own permissions in its pinned org
    and is treated as a non-member of every other org, so
    `assert_row_org_permission` turns another org's row into the view's
    own not-found.

    Cache seam: when a Redis cache lands later, it wraps the
    DB-fetch portion of resolve().
    """

    def resolve(self, user, org_id: int) -> EffectivePermissions:
        if is_pinned_org_principal(user):
            if org_id != user.pinned_org_id:
                raise OrgMembershipRequiredError()
            return user.resolve_effective_permissions(org_id)

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

        return EffectivePermissions.from_role(membership.role)
