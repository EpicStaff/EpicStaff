from __future__ import annotations

"""
Organization resolution helper for Flow Assistant views.

Priority order:
  0. USER API key → the key's org; the header is not read.
  1. X-Organization-Id header present → look up the specific OrganizationUser row.
     - Found → return it.
     - Not found → raise OrganizationMembershipNotFound (403).
  2. Header absent or empty → query all memberships for the user.
     - Exactly 1 → return it.
     - 0 → raise UserHasNoOrganizationMembership (400).
     - 2+ → raise OrganizationContextAmbiguous (400).

Always selects related 'org' and 'user' on the returned row.
"""

from rbac.access.principals import user_api_key_org_id
from rbac.exceptions import (
    OrganizationContextAmbiguous,
    OrganizationMembershipNotFound,
    UserHasNoOrganizationMembership,
)
from rbac.models.organization_user import OrganizationUser

# ── Public helper ─────────────────────────────────────────────────────────────


def resolve_organization_user(request) -> OrganizationUser:
    """Return the OrganizationUser for the authenticated request.

    Resolution order:
      0. USER API key → its org (403 if the owner is no longer a member).
      1. X-Organization-Id header present → targeted lookup (403 if not a member).
      2. Header absent → single-org fallback (400 if 0 or 2+ memberships).

    Always select_related('org', 'user') for callers that need org info.
    """
    org_id = user_api_key_org_id(request)
    if org_id is None:
        header_value = request.headers.get("X-Organization-Id", "").strip()
        if header_value:
            try:
                org_id = int(header_value)
            except ValueError as e:
                raise OrganizationMembershipNotFound(
                    detail=f"Invalid X-Organization-Id header value: '{header_value}'."
                ) from e

    if org_id is not None:
        try:
            return OrganizationUser.objects.select_related("org", "user").get(
                user=request.user,
                org_id=org_id,
            )
        except OrganizationUser.DoesNotExist as e:
            raise OrganizationMembershipNotFound() from e

    # No header — single-org fallback
    memberships = list(
        OrganizationUser.objects.select_related("org", "user").filter(user=request.user)
    )

    if len(memberships) == 0:
        raise UserHasNoOrganizationMembership()

    if len(memberships) == 1:
        return memberships[0]

    raise OrganizationContextAmbiguous()
