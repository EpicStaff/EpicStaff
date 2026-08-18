from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.permission_serializers import RoleResponseSerializer
from tables.services.rbac.authentication import ApiKeyAuthentication, JwtAuthentication
from tables.services.rbac.permissions import HasResourcePermissionAnywhere
from tables.services.rbac.rbac_exceptions import OrgContextRequiredError
from tables.services.rbac.role_management_service import RoleManagementService
from tables.services.rbac.role_validation_service import RoleValidationService
from tables.swagger_schemas.role_admin_schema import (
    ROLES_CREATE_POST,
    ROLES_DESTROY_DELETE,
    ROLES_LIST_GET,
    ROLES_RETRIEVE_GET,
    ROLES_UPDATE_PATCH,
)


class RolesPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class RoleAdminViewSet(viewsets.ViewSet):
    """Flat, permission-gated role management surface.

    list:            GET    /api/admin/roles/            (?org_ids= filter)
    retrieve:        GET    /api/admin/roles/{id}/
    create:          POST   /api/admin/roles/            (org_id in body)
    partial_update:  PATCH  /api/admin/roles/{id}/
    destroy:         DELETE /api/admin/roles/{id}/       (?dry_run=true previews)

    The door gate is HasResourcePermissionAnywhere(ROLES); precise per-org
    authorization + the ceiling rule are enforced in RoleManagementService.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, HasResourcePermissionAnywhere]
    pagination_class = RolesPagination
    lookup_value_regex = "[0-9]+"

    rbac_resource_type = ResourceType.ROLES
    rbac_action_map = {
        "list": Permission.READ,
        "retrieve": Permission.READ,
        "create": Permission.CREATE,
        "partial_update": Permission.UPDATE,
        "destroy": Permission.DELETE,
    }

    _service = RoleManagementService()
    _validator = RoleValidationService()

    @extend_schema(**ROLES_LIST_GET)
    def list(self, request):
        org_ids = self._parse_org_ids(request.query_params.get("org_ids"))
        scopes = getattr(request, "_rbac_org_scopes", None)
        custom_qs = self._service.list_custom_roles(
            actor=request.user, org_ids=org_ids, scopes=scopes
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(custom_qs, request, view=self)
        self._service.attach_role_display(roles=page)
        response = paginator.get_paginated_response(
            RoleResponseSerializer(page, many=True).data
        )
        built_ins = self._service.list_built_in_roles()
        response.data["built_in_roles"] = RoleResponseSerializer(
            built_ins, many=True
        ).data
        return response

    @extend_schema(**ROLES_RETRIEVE_GET)
    def retrieve(self, request, pk=None):
        role = self._service.get_role_for_read(actor=request.user, role_id=pk)
        return Response(RoleResponseSerializer(role).data)

    @extend_schema(**ROLES_CREATE_POST)
    def create(self, request):
        cleaned = self._validator.validate_create(request.data)
        role = self._service.create_role(
            actor=request.user,
            org_id=cleaned["org_id"],
            name=cleaned["name"],
            description=cleaned["description"],
            permissions=cleaned["permissions"],
        )
        return Response(
            RoleResponseSerializer(role).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(**ROLES_UPDATE_PATCH)
    def partial_update(self, request, pk=None):
        cleaned = self._validator.validate_update(request.data)
        role = self._service.update_role(
            actor=request.user, role_id=pk, changes=cleaned
        )
        return Response(RoleResponseSerializer(role).data)

    @extend_schema(**ROLES_DESTROY_DELETE)
    def destroy(self, request, pk=None):
        if self._is_truthy(request.query_params.get("dry_run")):
            preview = self._service.preview_delete(actor=request.user, role_id=pk)
            return Response(preview, status=status.HTTP_200_OK)
        reassigned = self._service.delete_role(actor=request.user, role_id=pk)
        return Response({"reassigned_count": reassigned}, status=status.HTTP_200_OK)

    @staticmethod
    def _parse_org_ids(raw):
        if not raw:
            return None
        try:
            return [int(part) for part in raw.split(",") if part != ""]
        except ValueError as exc:
            raise OrgContextRequiredError() from exc

    @staticmethod
    def _is_truthy(raw):
        return str(raw).strip().lower() in ("true", "1") if raw is not None else False
