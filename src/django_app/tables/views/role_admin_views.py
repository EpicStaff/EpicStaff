from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.permission_serializers import RoleResponseSerializer
from tables.services.rbac.authentication import JwtOrApiKeyAuthentication
from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permissions import HasOrgPermission
from tables.services.rbac.role_management_service import RoleManagementService


class RoleAdminViewSet(viewsets.ViewSet):
    """Active-context role read surface.

    list:     GET /api/admin/roles/        (X-Organization-Id header required)
    retrieve: GET /api/admin/roles/{id}/   (no header needed — self-resolves
              from role.org_id; built-ins are global, customs check membership)
    """

    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = RoleManagementService()
    _org_context = OrgContextService()

    @extend_schema(
        summary="List roles in the active organization",
        responses={200: RoleResponseSerializer(many=True)},
    )
    def list(self, request):
        org_id = self._org_context.resolve(request=request, view_kwargs={})
        roles = self._service.list_roles(org_id=org_id)
        return Response(
            RoleResponseSerializer(roles, many=True).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Single role with full permission matrix",
        responses={
            200: RoleResponseSerializer,
            404: OpenApiResponse(description="Role not found"),
        },
    )
    def retrieve(self, request, pk=None):
        role = self._service.get_role(role_id=pk)
        return Response(RoleResponseSerializer(role).data)


class OrgScopedRoleAdminViewSet(viewsets.ViewSet):
    """Target-context role read surface.

    list: GET /api/admin/organizations/{org_id}/roles/
    """

    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated, HasOrgPermission]

    rbac_resource_type = ResourceType.ROLES
    rbac_action_map = {"list": Permission.READ}

    _service = RoleManagementService()

    @extend_schema(
        summary="List roles for a specific organization (target-context)",
        responses={
            200: RoleResponseSerializer(many=True),
            404: OpenApiResponse(description="Organization not found"),
        },
    )
    def list(self, request, org_id=None):
        roles = self._service.list_roles(org_id=int(org_id))
        return Response(RoleResponseSerializer(roles, many=True).data)
