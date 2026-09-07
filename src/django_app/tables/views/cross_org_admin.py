from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from tables.services.rbac.authentication import ApiKeyAuthentication, JwtAuthentication
from tables.services.rbac.permissions import HasResourcePermissionAnywhere, IsSuperadmin
from tables.services.rbac.rbac_exceptions import OrgContextRequiredError


class CrossOrgAdminViewSet(viewsets.ViewSet):
    """Base for flat cross-org governance viewsets (roles, memberships, orgs).

    - **Door gate:** `HasResourcePermissionAnywhere(rbac_resource_type)` —
      resolved via `rbac_action_map` (subclass sets both). Coarse: passes if
      the caller holds the action in >=1 org; the service does the precise
      per-org check.
    - **Mixed gate:** any action named in `superadmin_actions` is gated by
      `IsSuperadmin` instead — for a resource's global/platform actions
      (e.g. create/deactivate an organization). The door gate never runs for
      those actions, so they need no `rbac_action_map` entry.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, HasResourcePermissionAnywhere]
    superadmin_actions = frozenset()
    lookup_value_regex = "[0-9]+"

    def get_permissions(self):
        if getattr(self, "action", None) in self.superadmin_actions:
            return [IsAuthenticated(), IsSuperadmin()]
        return super().get_permissions()

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
