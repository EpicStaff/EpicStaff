from django.core.exceptions import ImproperlyConfigured
from rest_framework.permissions import BasePermission

from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permission_action_map import DEFAULT_ACTION_MAP
from tables.services.rbac.permission_resolver import PermissionResolver


class IsSuperadmin(BasePermission):
    """Allows access only to authenticated users with `is_superadmin=True`.

    Pair with `IsAuthenticated` so anonymous callers get 401. Used on
    endpoints that are architecturally superadmin-only (org CRUD,
    grant/revoke superadmin, reset-user) — these stay separate from
    HasOrgPermission.
    """

    message = "Superadmin privileges are required for this action."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(
            user and user.is_authenticated and getattr(user, "is_superadmin", False)
        )


class HasOrgPermission(BasePermission):
    """Generic RBAC permission gate.

    Reads `rbac_resource_type` (required) and `rbac_action_map`
    (optional) from the view. Picks the required action from
    `view.action` via the per-view map first, the default map second.

    Order: must run AFTER `IsAuthenticated` in `permission_classes`.
    The class assumes `request.user.is_authenticated` and reads
    `request.user.is_superadmin`.

    Missing `rbac_resource_type` on the view raises ImproperlyConfigured
    so integration mistakes surface immediately.
    """

    _org_context = OrgContextService()
    _resolver = PermissionResolver()

    def has_permission(self, request, view):
        resource_type = getattr(view, "rbac_resource_type", None)
        if resource_type is None:
            raise ImproperlyConfigured(
                f"{view.__class__.__name__} uses HasOrgPermission but did not declare "
                "rbac_resource_type."
            )

        # Superadmin bypass — short-circuit before doing any DB work.
        if getattr(request.user, "is_superadmin", False):
            return True

        # Required action: per-view map > default map > deny.
        action_map = getattr(view, "rbac_action_map", None) or DEFAULT_ACTION_MAP
        action_name = getattr(view, "action", None)
        required = action_map.get(action_name) if action_name else None
        if required is None:
            return False

        org_id = self._org_context.resolve(request=request, view_kwargs=view.kwargs)
        effective = self._resolver.resolve(user=request.user, org_id=org_id)

        if not effective.can(resource_type, required):
            resource_str = (
                resource_type if isinstance(resource_type, str) else resource_type.value
            )
            self.message = (
                f"You do not have permission to {action_name} {resource_str}."
            )
            return False
        return True
