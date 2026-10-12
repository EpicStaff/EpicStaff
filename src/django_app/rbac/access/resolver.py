from rbac.access.effective import EffectivePermissions
from rbac.exceptions import OrgMembershipRequiredError
from rbac.models import OrganizationUser


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

        return EffectivePermissions.from_role(membership.role)

    def resolve_cached(self, request, org_id: int) -> EffectivePermissions:
        """Per-request memoization of `resolve` for the request's principal in `org_id`.

        The verb gate and later readers in the same request (serializers, actions)
        need the same permissions; caching them on the request resolves them once.
        Keyed by org, so permissions resolved for one org are never reused for
        another. Stored on the request object, so nothing outlives the request.
        `request.user` is the principal the authenticator chose (the key owner for
        a user API key, the system principal for a system key), as with `resolve`.

        NOTE: the cache is never invalidated. Code that changes the caller's own
        membership or role and then reads permissions in the same request must
        call `resolve`, not this.
        """
        cache = getattr(request, "_rbac_effective_by_org", None)
        if cache is None:
            cache = {}
            request._rbac_effective_by_org = cache
        if org_id not in cache:
            cache[org_id] = self.resolve(user=request.user, org_id=org_id)
        return cache[org_id]
