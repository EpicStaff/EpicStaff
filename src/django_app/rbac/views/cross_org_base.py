from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from rbac.access.gates import (
    HasResourcePermissionAnywhere,
    IsSuperadmin,
    RestrictApiKeyToUserKeyReads,
)
from rbac.access.principals import user_api_key_org_id
from rbac.exceptions import OrganizationNotFoundError, OrgContextRequiredError
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication


class CrossOrgAdminPagination(PageNumberPagination):
    """Paging for every cross-org governance list."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class CrossOrgAdminViewSet(viewsets.ViewSet):
    """Base for flat cross-org governance viewsets (roles, memberships, orgs, users,
    API keys, plugin role permissions).

    - **Door gate:** `HasResourcePermissionAnywhere(rbac_resource_type)` —
      resolved via `rbac_action_map` (subclass sets both). Coarse: passes if
      the caller holds the action in >=1 org; the service does the precise
      per-org check. A subclass may replace the door gate with its own
      `permission_classes` (`UserAdminViewSet` lists `IsSuperadmin` instead).
    - **Mixed gate:** any action named in `superadmin_actions` swaps the door
      gate for `IsSuperadmin` and keeps the rest of `permission_classes` —
      for a resource's global/platform actions (e.g. create/deactivate an
      organization). The door gate never runs for those actions, so they
      need no `rbac_action_map` entry.
    - **API-key gate:** `RestrictApiKeyToUserKeyReads` runs first on every
      action of every subclass. It is prepended here rather than listed in
      `permission_classes`, so neither a subclass's `permission_classes` nor
      an `@action(permission_classes=...)` can drop it: writes are JWT-only
      and the SYSTEM key is rejected outright.
    - **API-key org:** a USER key (a superadmin's too) acts only in its own
      org. Views take the orgs they read through `requested_org_ids`,
      `key_org_ids`, `key_org_id` and `require_key_org`, never from the
      query directly.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, HasResourcePermissionAnywhere]
    superadmin_actions = frozenset()
    lookup_value_regex = "[0-9]+"

    def get_permissions(self):
        permissions = super().get_permissions()
        if getattr(self, "action", None) in self.superadmin_actions:
            permissions = [
                permission
                for permission in permissions
                if not isinstance(permission, HasResourcePermissionAnywhere)
            ]
            permissions.append(IsSuperadmin())
        return [RestrictApiKeyToUserKeyReads(), *permissions]

    @staticmethod
    def parse_org_ids(raw):
        """Parse a comma-separated `?org_ids=` value into a list[int], or None
        when absent. A non-integer value is a 400 (`org_context_required`)."""
        if not raw:
            return None
        try:
            return [int(part) for part in raw.split(",") if part != ""]
        except ValueError as exc:
            raise OrgContextRequiredError() from exc

    def requested_org_ids(self, request, param="org_ids"):
        """Return the orgs the `param` query names, or `[key org]` for a USER API key.

        Whatever a USER key's request asks for, or nothing at all, becomes the key's org.
        The value is parsed first either way, so a malformed one is a 400 for a key too.
        """
        org_ids = self.parse_org_ids(request.query_params.get(param))
        return self.key_org_ids(request) or org_ids

    def key_org_id(self, request):
        """Return the org of the request's USER API key, or None for any other credential."""
        return user_api_key_org_id(request)

    def key_org_ids(self, request):
        """Return `[key org]` for a USER API key request, else None (no limit)."""
        key_org_id = self.key_org_id(request)
        return None if key_org_id is None else [key_org_id]

    def require_key_org(self, request, org_id):
        """Raise OrganizationNotFoundError when a USER API key's org is not `org_id`.

        Another org is answered as missing, so the key learns nothing about it.
        """
        key_org_id = self.key_org_id(request)
        if key_org_id is not None and key_org_id != org_id:
            raise OrganizationNotFoundError()
