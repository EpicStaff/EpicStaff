from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tables.services.rbac.authentication import ApiKeyAuthentication, JwtAuthentication
from tables.services.rbac.cross_org_permission_resolver import (
    CrossOrgPermissionResolver,
)
from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permission_catalog import build_catalog
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.swagger_schemas.permission_schema import (
    PERMISSIONS_CATALOG_GET,
    PERMISSIONS_ME_GET,
    PERMISSIONS_ME_ORGS_GET,
)


class PermissionCatalogView(APIView):
    """Static permission taxonomy. Drives the FE matrix UI."""

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(**PERMISSIONS_CATALOG_GET)
    def get(self, request):
        return Response(build_catalog())


class MyPermissionsView(APIView):
    """Caller's effective permissions in the active org (header)."""

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _org_context = OrgContextService()
    _resolver = PermissionResolver()

    @extend_schema(**PERMISSIONS_ME_GET)
    def get(self, request):
        org_id = self._org_context.resolve(request=request, view_kwargs={})
        effective = self._resolver.resolve(user=request.user, org_id=org_id)
        role_payload = (
            None
            if effective.role is None
            else {"id": effective.role.id, "name": effective.role.name}
        )
        return Response(
            {
                "org_id": org_id,
                "is_superadmin": effective.is_superadmin,
                "role": role_payload,
                "permissions": effective.to_action_codes(),
            }
        )


class MyOrgsPermissionsView(APIView):
    """Caller's effective permissions across every org they belong to.

    Superadmin short-circuits to a wildcard without enumerating orgs.
    No X-Organization-Id header — this endpoint is inherently multi-org.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _resolver = CrossOrgPermissionResolver()

    @extend_schema(**PERMISSIONS_ME_ORGS_GET)
    def get(self, request):
        if getattr(request.user, "is_superadmin", False):
            return Response({"is_superadmin": True, "permissions": "*"})

        scopes = self._resolver.resolve_all(user=request.user)
        orgs = [
            {
                "org": {"id": scope.org.id, "name": scope.org.name},
                "role": (
                    None
                    if scope.effective.role is None
                    else {
                        "id": scope.effective.role.id,
                        "name": scope.effective.role.name,
                    }
                ),
                "permissions": scope.effective.to_action_codes(),
            }
            for scope in scopes
        ]
        return Response({"is_superadmin": False, "orgs": orgs})
