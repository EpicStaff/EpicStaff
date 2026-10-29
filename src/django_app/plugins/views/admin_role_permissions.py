from rbac.access.principals import limit_org_ids_to_api_key, user_api_key_org_id
from rbac.models.enums import Permission, ResourceType
from rbac.views.cross_org_base import CrossOrgAdminViewSet
from rest_framework.response import Response

from plugins.access.role_permission_service import PluginRolePermissionService
from plugins.serializers.role_permissions import (
    OptionalOrganizationQuerySerializer,
    PluginRolePermissionsResponseSerializer,
    PluginRolePermissionsUpdateSerializer,
    PluginRoleRowsResponseSerializer,
    RequiredOrganizationQuerySerializer,
)


class PluginRolePermissionViewSet(CrossOrgAdminViewSet):
    """The plugin rows of the Roles matrix.

    rows:      GET /api/admin/plugin-role-permissions/rows/?org_id=<id>   (a role not saved yet)
    retrieve:  GET /api/admin/plugin-role-permissions/{role_id}/[?org_id=<id>]
    update:    PUT /api/admin/plugin-role-permissions/{role_id}/          (full replacement)

    A cross-org admin surface: the organization comes from the query or the role, never
    `X-Organization-Id`. `CrossOrgAdminViewSet` pins JWT and API-key authentication (so no
    plugin credential ever authenticates here), admits an API key only on reads and only as
    a USER key (every write is JWT-only), and runs the coarse roles door gate; the service
    authorizes each organization and role precisely.
    """

    rbac_resource_type = ResourceType.ROLES
    rbac_action_map = {
        "rows": Permission.READ,
        "retrieve": Permission.READ,
        "update": Permission.UPDATE,
    }

    _service = PluginRolePermissionService()

    def rows(self, request):
        # A key caller's org is its key's, so `?org_id=` is neither required nor read.
        org_id = user_api_key_org_id(request)
        if org_id is None:
            query = RequiredOrganizationQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            org_id = query.validated_data["org_id"]
        result = self._service.rows_for_organization(request.user, org_id)
        return Response(PluginRoleRowsResponseSerializer(result).data)

    def retrieve(self, request, role_id: int):
        org_id = user_api_key_org_id(request)
        if org_id is None:
            query = OptionalOrganizationQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            org_id = query.validated_data.get("org_id")
        result = self._service.role_permissions(
            request.user,
            role_id,
            org_id,
            scopes=getattr(request, "_rbac_org_scopes", None),
            limit_to_org_ids=limit_org_ids_to_api_key(request, None),
        )
        return Response(PluginRolePermissionsResponseSerializer(result).data)

    def update(self, request, role_id: int):
        body = PluginRolePermissionsUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        result = self._service.replace_role_permissions(
            request.user, role_id, body.validated_data["plugins"]
        )
        return Response(PluginRolePermissionsResponseSerializer(result).data)
