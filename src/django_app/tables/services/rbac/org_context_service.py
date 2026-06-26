from typing import Optional

from tables.models.rbac_models import OrganizationUser
from tables.services.rbac.rbac_exceptions import (
    OrgContextRequiredError,
    OrgMembershipRequiredError,
)


class OrgContextService:
    """OrgContextService — resolves the active org for a request.

    Resolution order:
    1. URL kwarg `org_id` (target-context wins on nested admin endpoints).
    2. `X-Organization-Id` header (active-context).

    Validates the caller has a membership in the resolved org. Superadmin
    bypasses membership but the org must still exist as a real id.

    Errors:
    - Missing or malformed source: OrgContextRequiredError (400).
    - Caller not a member and not superadmin: OrgMembershipRequiredError (403).
    - Caller is non-superadmin and the org is inactive: OrgMembershipRequiredError.
    """

    def resolve(self, request, view_kwargs: Optional[dict] = None) -> int:
        org_id = self._extract_org_id(request=request, view_kwargs=view_kwargs)
        self._assert_membership(user=request.user, org_id=org_id)
        return org_id

    def _extract_org_id(self, request, view_kwargs) -> int:
        if view_kwargs and "org_id" in view_kwargs:
            try:
                return int(view_kwargs["org_id"])
            except (TypeError, ValueError) as exc:
                raise OrgContextRequiredError() from exc

        header = (
            request.headers.get("X-Organization-Id")
            if hasattr(request, "headers")
            else None
        )
        if not header:
            raise OrgContextRequiredError()
        try:
            return int(header)
        except (TypeError, ValueError) as exc:
            raise OrgContextRequiredError() from exc

    def _assert_membership(self, user, org_id: int) -> None:
        if getattr(user, "is_superadmin", False):
            return
        exists = OrganizationUser.objects.filter(
            user=user, org_id=org_id, org__is_active=True
        ).exists()
        if not exists:
            raise OrgMembershipRequiredError()
