from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tables.serializers.permission_serializers import (
    CatalogResponseSerializer,
    PermissionsMeResponseSerializer,
)
from tables.services.rbac.authentication import JwtOrApiKeyAuthentication
from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permission_catalog import (
    ACTION_METADATA,
    RESOURCE_TYPE_METADATA,
)
from tables.services.rbac.permission_resolver import PermissionResolver


class PermissionCatalogView(APIView):
    """Static permission taxonomy. Drives the FE matrix UI."""

    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Permission catalog (resource types, actions, applicable map)",
        responses={200: CatalogResponseSerializer},
    )
    def get(self, request):
        return Response(
            {
                "actions": ACTION_METADATA,
                "resource_types": RESOURCE_TYPE_METADATA,
            }
        )


class MyPermissionsView(APIView):
    """Caller's effective permissions in the active org (header)."""

    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _org_context = OrgContextService()
    _resolver = PermissionResolver()

    @extend_schema(
        summary="Effective permissions for the caller in the active org",
        responses={200: PermissionsMeResponseSerializer},
    )
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
