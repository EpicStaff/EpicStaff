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
