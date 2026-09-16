from dataclasses import dataclass

from django.db.models.functions import Lower

from tables.models.rbac_models import Organization, OrganizationUser
from tables.services.rbac.effective_permissions import EffectivePermissions


@dataclass
class OrgScope:
    """The caller's resolved permissions in one organization."""

    org: Organization
    effective: EffectivePermissions


class CrossOrgPermissionResolver:
    """Resolves a user's effective permissions across every org they
    belong to. The single source of truth for cross-org capability
    questions ("where can I do X?").

    `resolve_all` assumes a NON-superadmin caller — superadmin bypass is
    handled by callers (they short-circuit before enumerating orgs, since
    superadmin authority is org-independent).
    """

    def resolve_all(self, user) -> list[OrgScope]:
        memberships = (
            OrganizationUser.objects.select_related("org", "role")
            .prefetch_related("role__permissions_set")
            .filter(user=user, org__is_active=True)
            .order_by(Lower("org__name"))
        )
        return [
            OrgScope(org=m.org, effective=EffectivePermissions.from_role(m.role))
            for m in memberships
        ]

    def resolve_all_cached(self, request) -> list[OrgScope]:
        """Per-request memoization of `resolve_all` for the request's user.

        The cross-org door gate and the roles list both need the caller's
        scopes within a single request; caching them on the request object
        computes `resolve_all` once instead of twice.
        Superadmin never reaches here — the gate short-circuits before it."""
        cached = getattr(request, "_rbac_org_scopes", None)
        if cached is None:
            cached = self.resolve_all(user=request.user)
            request._rbac_org_scopes = cached
        return cached
