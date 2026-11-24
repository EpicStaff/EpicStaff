from rbac.access.principals import (
    PinnedOrgPrincipal,
    is_pinned_org_principal,
    user_api_key_org_id,
)
from rbac.exceptions import (
    OrganizationNotFoundError,
    OrgContextRequiredError,
    OrgDeactivatedError,
    OrgMembershipRequiredError,
)
from rbac.models import Organization, OrganizationUser


class OrgContextService:
    """OrgContextService — resolves the active org for a request.

    Resolution order:
    0. USER API key: the key's own org. Neither the URL kwarg nor the header is
       read, so a request naming another org silently acts in the key's org.
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
      For a USER key this is the owner who has left the key's org.
    - Caller is a member or superadmin and the org is inactive: OrgDeactivatedError (403).
    - Caller is superadmin and the org id does not exist: OrganizationNotFoundError (404).
    - Pinned principal naming another org: OrganizationNotFoundError (404).
    - Pinned principal whose pinned org is inactive: OrgDeactivatedError (403).
    """

    def resolve(self, request, view_kwargs: dict | None = None) -> int:
        requested_org_id = user_api_key_org_id(request)
        if requested_org_id is None:
            requested_org_id = self._extract_org_id(request=request, view_kwargs=view_kwargs)
        user = request.user
        if is_pinned_org_principal(user):
            return self._resolve_pinned(principal=user, requested_org_id=requested_org_id)
        if requested_org_id is None:
            raise OrgContextRequiredError()
        self.assert_membership(user=user, org_id=requested_org_id)
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
        """Return the principal's pinned org; refuse a request naming another or an inactive one.

        An inactive pinned org is named as such: the principal is bound to that org and
        already knows its id, so saying it is deactivated leaks nothing. Another org is
        answered as missing, whatever its state.
        """
        org_id = principal.pinned_org_id
        if requested_org_id is not None and requested_org_id != org_id:
            raise OrganizationNotFoundError()
        if not Organization.objects.filter(id=org_id, is_active=True).exists():
            raise OrgDeactivatedError()
        return org_id

    def assert_membership(self, user, org_id: int, *, lock: bool = False) -> None:
        """Require `user` to act in `org_id`: a member of it while it is active, or a superadmin.

        Args:
            lock: Hold the membership row `FOR UPDATE` until the caller's transaction
                ends, so a concurrent removal of the membership waits for it. Needs an
                open transaction. A superadmin has no membership row to lock.

        Raises:
            OrgDeactivatedError: A member or a superadmin named an inactive org.
            OrgMembershipRequiredError: Not a member and not a superadmin.
            OrganizationNotFoundError: A superadmin named an org that does not exist.
        """
        if getattr(user, "is_superadmin", False):
            org = Organization.objects.filter(id=org_id).values("is_active").first()

            if org is None:
                raise OrganizationNotFoundError()
            if not org["is_active"]:
                raise OrgDeactivatedError()
            return
        memberships = OrganizationUser.objects.filter(user=user, org_id=org_id, org__is_active=True)
        if lock:
            memberships = memberships.select_for_update(of=("self",))
        if memberships.values_list("pk", flat=True).first() is None:
            raise membership_refusal(user=user, org_id=org_id)


def membership_refusal(user, org_id: int) -> OrgMembershipRequiredError:
    """Return the error refusing a non-superadmin `user` with no active membership in `org_id`.

    Call it only once the active-membership lookup came back empty. A membership row
    found now normally means the org is inactive, and its member may be told so;
    anyone else gets the plain refusal, which reveals neither that the org exists nor
    its state. One query, on the refusal path only.

    The lookup is a second query, not locked against the first: a membership added or
    the org reactivated in between also yields `OrgDeactivatedError`, for an org that is
    active by now. That is accepted: the error still goes only to a member of the org,
    and a retry succeeds.
    """
    if OrganizationUser.objects.filter(user=user, org_id=org_id).exists():
        return OrgDeactivatedError()
    return OrgMembershipRequiredError()


def cache_active_org_id(request, org_id: int | None) -> None:
    """Cache the request's resolved active org under `_rbac_active_org_id`.

    Set on DRF's Request and on the HttpRequest beneath it: the scoping mixins, the
    serializer fields and `HasOrgPermission` read the former, middleware sees only the
    latter.
    """
    request._rbac_active_org_id = org_id
    http_request = getattr(request, "_request", None)
    if http_request is not None:
        http_request._rbac_active_org_id = org_id
