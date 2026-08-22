from __future__ import annotations

"""
Organization resolution helper for Flow Assistant views.

Priority order:
  1. X-Organization-Id header present → look up the specific OrganizationUser row.
     - Found → return it.
     - Not found → raise OrganizationMembershipNotFound (403).
  2. Header absent or empty → query all memberships for the user.
     - Exactly 1 → return it.
     - 0 → raise UserHasNoOrganizationMembership (400).
     - 2+ → raise OrganizationContextAmbiguous (400).

Always selects related 'org' and 'user' on the returned row.
"""

from tables.models.rbac_models.organization_user import OrganizationUser
from .rbac_exceptions import (
    OrganizationMembershipNotFound,
    UserHasNoOrganizationMembership,
    OrganizationContextAmbiguous,
)


# ── Public helper ─────────────────────────────────────────────────────────────


def resolve_organization_user(request) -> OrganizationUser:
    """Return the OrganizationUser for the authenticated request.

    Resolution order:
      1. X-Organization-Id header present → targeted lookup (403 if not a member).
      2. Header absent → single-org fallback (400 if 0 or 2+ memberships).

    Always select_related('org', 'user') for callers that need org info.
    """
    header_value = request.headers.get("X-Organization-Id", "").strip()

    if header_value:
        try:
            org_id = int(header_value)
        except ValueError:
            raise OrganizationMembershipNotFound(
                detail=f"Invalid X-Organization-Id header value: '{header_value}'."
            )

        try:
            return OrganizationUser.objects.select_related("org", "user").get(
                user=request.user,
                org_id=org_id,
            )
        except OrganizationUser.DoesNotExist:
            raise OrganizationMembershipNotFound()

    # No header — single-org fallback
    memberships = list(
        OrganizationUser.objects.select_related("org", "user").filter(user=request.user)
    )

    if len(memberships) == 0:
        raise UserHasNoOrganizationMembership()

    if len(memberships) == 1:
        return memberships[0]

    raise OrganizationContextAmbiguous()
