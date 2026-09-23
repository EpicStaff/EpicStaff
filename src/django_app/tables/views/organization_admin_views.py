import dataclasses

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.delete_serializers import OrganizationDeleteReportSerializer
from tables.serializers.organization_serializers import (
    OrganizationListResponseSerializer,
    OrganizationResponseSerializer,
)
from tables.services.rbac.organization_management_service import (
    OrganizationManagementService,
)
from tables.services.rbac.organization_validation_service import (
    OrganizationValidationService,
)
from tables.services.rbac.permissions import DenyApiKeyAuth
from tables.swagger_schemas.organization_admin_schema import (
    ORGANIZATIONS_CREATE_POST,
    ORGANIZATIONS_DEACTIVATE_POST,
    ORGANIZATIONS_DESTROY_DELETE,
    ORGANIZATIONS_LIST_GET,
    ORGANIZATIONS_REACTIVATE_POST,
    ORGANIZATIONS_RETRIEVE_GET,
    ORGANIZATIONS_UPDATE_PATCH,
)
from tables.views.cross_org_admin import CrossOrgAdminPagination, CrossOrgAdminViewSet

_ORG_ORDERING_WHITELIST = {
    "name": "name",
    "created_at": "created_at",
    "member_count": "member_count",
}


class OrganizationAdminViewSet(CrossOrgAdminViewSet):
    """Adaptive management of Organizations.

    list / retrieve / partial_update are permission-aware (ORGANIZATIONS bits;
    superadmin sees all). create / deactivate / reactivate are platform-level
    and stay superadmin-only via `superadmin_actions`.

    Domain errors (404 not-found, 400 name-conflict, 400 last-active-org) are
    raised by the service layer as CustomAPIExeption subclasses and rendered
    through the project's `custom_exception_handler` envelope; the view layer
    does not catch or translate them.
    """

    superadmin_actions = frozenset({"create", "deactivate", "reactivate", "destroy"})
    pagination_class = CrossOrgAdminPagination
    rbac_resource_type = ResourceType.ORGANIZATIONS
    rbac_action_map = {
        "list": Permission.READ,
        "retrieve": Permission.READ,
        "partial_update": Permission.UPDATE,
    }

    _service = OrganizationManagementService()
    _validator = OrganizationValidationService()

    def get_permissions(self):
        """Permanent deletion is JWT-only; a leaked key must not erase a tenant."""
        permissions = super().get_permissions()
        if getattr(self, "action", None) == "destroy":
            return permissions + [DenyApiKeyAuth()]
        return permissions

    @extend_schema(**ORGANIZATIONS_LIST_GET)
    def list(self, request):
        is_active = self._parse_is_active(request.query_params.get("is_active"))
        org_ids = self.parse_org_ids(request.query_params.get("org_ids"))
        scopes = getattr(request, "_rbac_org_scopes", None)
        qs = self._service.list_for_actor(
            actor=request.user,
            is_active=is_active,
            search=request.query_params.get("search"),
            org_ids=org_ids,
            scopes=scopes,
        )
        qs = self._apply_ordering(qs, request.query_params.get("ordering"))
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        self._service.attach_admins(
            page,
            include_superadmin_fallback=getattr(request.user, "is_superadmin", False),
        )
        return paginator.get_paginated_response(
            OrganizationListResponseSerializer(page, many=True, context={"request": request}).data
        )

    @extend_schema(**ORGANIZATIONS_RETRIEVE_GET)
    def retrieve(self, request, pk=None):
        org = self._service.get_for_read(actor=request.user, org_id=int(pk))
        return Response(OrganizationResponseSerializer(org).data)

    @extend_schema(**ORGANIZATIONS_CREATE_POST)
    def create(self, request):
        cleaned = self._validator.validate_create(request.data)
        org = self._service.create_organization(name=cleaned["name"])
        return Response(
            OrganizationResponseSerializer(org).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(**ORGANIZATIONS_UPDATE_PATCH)
    def partial_update(self, request, pk=None):
        cleaned = self._validator.validate_rename(request.data)
        org = self._service.rename_organization(
            actor=request.user, org_id=int(pk), name=cleaned["name"]
        )
        return Response(OrganizationResponseSerializer(org).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    @extend_schema(**ORGANIZATIONS_DEACTIVATE_POST)
    def deactivate(self, request, pk=None):
        org = self._service.deactivate_organization(org_id=int(pk))
        return Response(OrganizationResponseSerializer(org).data)

    @action(detail=True, methods=["post"], url_path="reactivate")
    @extend_schema(**ORGANIZATIONS_REACTIVATE_POST)
    def reactivate(self, request, pk=None):
        org = self._service.reactivate_organization(org_id=int(pk))
        return Response(OrganizationResponseSerializer(org).data)

    @extend_schema(**ORGANIZATIONS_DESTROY_DELETE)
    def destroy(self, request, pk=None):
        """Permanently delete an organization and everything it owns, or preview the deletion."""
        if self._is_truthy(request.query_params.get("dry_run")):
            report = self._service.preview_delete(actor=request.user, org_id=int(pk))
        else:
            report = self._service.delete_organization(actor=request.user, org_id=int(pk))
        return Response(OrganizationDeleteReportSerializer(dataclasses.asdict(report)).data)

    def _apply_ordering(self, qs, raw):
        if not raw:
            return qs  # default: -is_active, name (from _list_organizations)
        descending = raw.startswith("-")
        key = raw.lstrip("-")
        field = _ORG_ORDERING_WHITELIST.get(key)
        if field is None:
            return qs
        return qs.order_by(f"-{field}" if descending else field, "id")

    @staticmethod
    def _parse_is_active(value):
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
        return None

    @staticmethod
    def _is_truthy(raw):
        return str(raw).strip().lower() in ("true", "1") if raw is not None else False
