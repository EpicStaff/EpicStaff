from rbac.access.principals import PinnedOrgPrincipal, is_pinned_org_principal
from rbac.exceptions import (
    OrganizationNotFoundError,
    OrgContextRequiredError,
    OrgMembershipRequiredError,
)
from rbac.models import Organization, OrganizationUser


class OrgContextService:
    """OrgContextService — resolves the active org for a request.

    Resolution order:
    1. URL kwarg `org_id` (target-context wins on nested admin endpoints).
    2. `X-Organization-Id` header (active-context).

    Validates the caller has a membership in the resolved org. Superadmin
    bypasses membership but the org must still exist as a real id.

    A `PinnedOrgPrincipal` needs neither source: without one, its active org
    is its pinned org. Naming any other org is answered as if that org did not
    exist, so the principal learns nothing about other orgs.

    Errors:
    - Missing or malformed source: OrgContextRequiredError (400).
    - Caller not a member and not superadmin: OrgMembershipRequiredError (403).
    - Caller is non-superadmin and the org is inactive: OrgMembershipRequiredError.
    - Caller is superadmin and the org id does not exist: OrganizationNotFoundError (404).
    - Pinned principal naming another org: OrganizationNotFoundError (404).
    - Pinned principal whose pinned org is inactive: OrgMembershipRequiredError.
    """

    def resolve(self, request, view_kwargs: dict | None = None) -> int:
        requested_org_id = self._extract_org_id(request=request, view_kwargs=view_kwargs)
        user = request.user
        if is_pinned_org_principal(user):
            return self._resolve_pinned(principal=user, requested_org_id=requested_org_id)
        if requested_org_id is None:
            raise OrgContextRequiredError()
        self._assert_membership(user=user, org_id=requested_org_id)
        return requested_org_id

    def _extract_org_id(self, request, view_kwargs) -> int | None:
        """The org id the request names, or None when it names none."""
        if view_kwargs and "org_id" in view_kwargs:
            try:
                return int(view_kwargs["org_id"])
            except (TypeError, ValueError) as exc:
                raise OrgContextRequiredError() from exc

        header = request.headers.get("X-Organization-Id") if hasattr(request, "headers") else None
        if not header:
            return None
        try:
            return int(header)
        except (TypeError, ValueError) as exc:
            raise OrgContextRequiredError() from exc

    def _resolve_pinned(self, principal: PinnedOrgPrincipal, requested_org_id: int | None) -> int:
        org_id = principal.pinned_org_id
        if requested_org_id is not None and requested_org_id != org_id:
            raise OrganizationNotFoundError()
        if not Organization.objects.filter(id=org_id, is_active=True).exists():
            raise OrgMembershipRequiredError()
        return org_id

    def _assert_membership(self, user, org_id: int) -> None:
        if getattr(user, "is_superadmin", False):
            org = Organization.objects.filter(id=org_id).values("is_active").first()

            if org is None:
                raise OrganizationNotFoundError()
            if not org["is_active"]:
                raise OrgMembershipRequiredError()
            return
        exists = OrganizationUser.objects.filter(
            user=user, org_id=org_id, org__is_active=True
        ).exists()
        if not exists:
            raise OrgMembershipRequiredError()
