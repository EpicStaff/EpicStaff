from django.core.exceptions import ImproperlyConfigured
from rest_framework.permissions import BasePermission, SAFE_METHODS

from tables.models.rbac_models import ApiKey
from tables.services.rbac.cross_org_permission_resolver import (
    CrossOrgPermissionResolver,
)
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


class IsSuperadminOrReadOnly(BasePermission):
    """Authenticated users may read (safe methods); only superadmins may write.

    Method-based companion to `SuperadminWriteMixin` for **global** resources
    exposed as plain APIViews (default-* config singletons, voice/Twilio
    settings) where there is no DRF `action`. Reads stay open to any
    authenticated user; create/update/delete require `is_superadmin`.
    """

    message = "Superadmin privileges are required to modify this resource."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(user, "is_superadmin", False))


class BaseRbacPermission(BasePermission):
    """Shared skeleton for RBAC verb gates (Template Method).

    Handles the parts every gate does the same way — the
    `rbac_resource_type` config guard, the superadmin bypass, and
    resolving the required action from the view's action map
    (`rbac_action_map` first, `DEFAULT_ACTION_MAP` second). Subclasses
    implement the single varying step, `_authorize`: a single-org check
    (`HasOrgPermission`) vs a cross-org "anywhere" check
    (`HasResourcePermissionAnywhere`).

    Missing `rbac_resource_type` raises ImproperlyConfigured so
    integration mistakes surface immediately.

    Order: must run AFTER `IsAuthenticated` in `permission_classes` —
    assumes `request.user.is_authenticated` and reads
    `request.user.is_superadmin`.
    """

    def has_permission(self, request, view):
        resource_type = getattr(view, "rbac_resource_type", None)
        if resource_type is None:
            raise ImproperlyConfigured(
                f"{view.__class__.__name__} uses {self.__class__.__name__} but did "
                "not declare rbac_resource_type."
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

        return self._authorize(
            request=request, view=view, resource_type=resource_type, required=required
        )

    def _authorize(self, request, view, resource_type, required) -> bool:
        """Return True iff the caller is authorized for `required` on
        `resource_type`. The one step that differs per gate."""
        raise NotImplementedError


class HasOrgPermission(BaseRbacPermission):
    """Single-org RBAC gate.

    Authorizes `required` against the caller's permissions in the
    request's **active org**, resolved from the URL kwarg `org_id` or the
    `X-Organization-Id` header (via OrgContextService).
    """

    _org_context = OrgContextService()
    _resolver = PermissionResolver()

    def _authorize(self, request, view, resource_type, required) -> bool:
        org_id = self._org_context.resolve(request=request, view_kwargs=view.kwargs)
        effective = self._resolver.resolve(user=request.user, org_id=org_id)

        if not effective.can(resource_type, required):
            resource_str = (
                resource_type if isinstance(resource_type, str) else resource_type.value
            )
            action_name = getattr(view, "action", None)
            self.message = (
                f"You do not have permission to {action_name} {resource_str}."
            )
            return False
        return True


class DenyApiKeyAuth(BasePermission):
    """Blocks API-key-authenticated callers.

    Key management is JWT-only: a (possibly leaked) credential must not be
    able to mint or destroy credentials. Pair AFTER IsAuthenticated.
    """

    message = "API keys cannot be used to manage API keys. Authenticate with a user session (JWT)."

    def has_permission(self, request, view):
        return not isinstance(request.auth, ApiKey)


class HasResourcePermissionAnywhere(BaseRbacPermission):
    """Cross-org door gate.

    Passes if the caller holds the required action on
    `view.rbac_resource_type` in AT LEAST ONE org. This is a coarse
    pre-filter — precise per-org authorization (specific target org +
    ceiling) is enforced in the service layer.
    """

    _resolver = CrossOrgPermissionResolver()

    def _authorize(self, request, view, resource_type, required) -> bool:
        scopes = self._resolver.resolve_all(user=request.user)
        return any(scope.effective.can(resource_type, required) for scope in scopes)
