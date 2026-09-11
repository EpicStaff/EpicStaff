from typing import Optional

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.api_key_serializers import ApiKeyAdminSerializer
from tables.services.rbac.api_key.management_service import ApiKeyManagementService
from tables.services.rbac.api_key.validation import ApiKeyValidationService
from tables.services.rbac.permissions import (
    DenyApiKeyAuth,
    HasResourcePermissionAnywhere,
)
from tables.swagger_schemas.api_key_schema import (
    API_KEYS_MANAGEMENT_DELETE,
    API_KEYS_MANAGEMENT_LIST,
    API_KEYS_MANAGEMENT_REVOKE_POST,
)
from tables.views.cross_org_admin import CrossOrgAdminPagination, CrossOrgAdminViewSet


class ApiKeyAdminViewSet(CrossOrgAdminViewSet):
    """Flat, permission-gated cross-org API-key surface.

    JWT only: a credential must not retire credentials. DenyApiKeyAuth is
    safe here only while `superadmin_actions` stays empty.
    """

    pagination_class = CrossOrgAdminPagination
    permission_classes = [
        IsAuthenticated,
        DenyApiKeyAuth,
        HasResourcePermissionAnywhere,
    ]
    rbac_resource_type = ResourceType.API_KEYS
    rbac_action_map = {
        "list": Permission.READ,
        "revoke": Permission.DELETE,
        "destroy": Permission.DELETE,
    }

    _service = ApiKeyManagementService()
    _validator = ApiKeyValidationService()

    @extend_schema(**API_KEYS_MANAGEMENT_LIST)
    def list(self, request):
        org_ids: Optional[list[int]] = self.parse_org_ids(
            request.query_params.get("org_ids")
        )
        filters: dict = self._validator.validate_list_keys_query(request.query_params)
        scopes = getattr(request, "_rbac_org_scopes", None)
        qs = self._service.list_keys(
            actor=request.user,
            org_ids=org_ids,
            owner_id=filters["owner_id"],
            status_value=filters["status_value"],
            search=filters["search"],
            scopes=scopes,
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        self._service.attach_visible_orgs(keys=page, actor=request.user, scopes=scopes)
        return paginator.get_paginated_response(
            ApiKeyAdminSerializer(page, many=True, context={"request": request}).data
        )

    @action(detail=True, methods=["post"], url_path="revoke")
    @extend_schema(**API_KEYS_MANAGEMENT_REVOKE_POST)
    def revoke(self, request, pk=None):
        scopes = getattr(request, "_rbac_org_scopes", None)
        key = self._service.revoke_key(
            actor=request.user, key_id=int(pk), scopes=scopes
        )
        self._service.attach_visible_orgs(keys=[key], actor=request.user, scopes=scopes)
        return Response(ApiKeyAdminSerializer(key, context={"request": request}).data)

    @extend_schema(**API_KEYS_MANAGEMENT_DELETE)
    def destroy(self, request, pk=None):
        self._service.delete_key(
            actor=request.user,
            key_id=int(pk),
            scopes=getattr(request, "_rbac_org_scopes", None),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
