from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rbac.access.catalog import build_catalog
from rbac.access.cross_org_resolver import (
    CrossOrgPermissionResolver,
)
from rbac.access.org_context import OrgContextService
from rbac.access.principals import user_api_key_org_id
from rbac.access.resolver import PermissionResolver
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rbac.schemas.permissions import (
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
    A USER API key acts only in its own org, so its caller (a superadmin too)
    gets `orgs` with that org alone.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _resolver = CrossOrgPermissionResolver()

    @extend_schema(**PERMISSIONS_ME_ORGS_GET)
    def get(self, request):
        is_superadmin = bool(getattr(request.user, "is_superadmin", False))
        key_org_id = user_api_key_org_id(request)
        if key_org_id is not None:
            scopes = self._resolver.resolve_in_org(user=request.user, org_id=key_org_id)
        elif is_superadmin:
            return Response({"is_superadmin": True, "permissions": "*"})
        else:
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
        return Response({"is_superadmin": is_superadmin, "orgs": orgs})
