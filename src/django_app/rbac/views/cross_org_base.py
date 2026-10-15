from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from rbac.access.gates import (
    HasResourcePermissionAnywhere,
    IsSuperadmin,
    RestrictApiKeyToUserKeyReads,
)
from rbac.exceptions import OrgContextRequiredError
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication


class CrossOrgAdminPagination(PageNumberPagination):
    """Paging for every cross-org governance list."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class CrossOrgAdminViewSet(viewsets.ViewSet):
    """Base for flat cross-org governance viewsets (roles, memberships, orgs, API keys).

    - **Door gate:** `HasResourcePermissionAnywhere(rbac_resource_type)` —
      resolved via `rbac_action_map` (subclass sets both). Coarse: passes if
      the caller holds the action in >=1 org; the service does the precise
      per-org check.
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
