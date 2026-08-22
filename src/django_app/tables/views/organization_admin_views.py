from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tables.serializers.organization_serializers import (
    OrganizationCreateRequestSerializer,
    OrganizationListResponseSerializer,
    OrganizationRenameRequestSerializer,
    OrganizationResponseSerializer,
)
from tables.services.rbac.authentication import ApiKeyAuthentication, JwtAuthentication
from tables.services.rbac.organization_management_service import (
    OrganizationManagementService,
)
from tables.services.rbac.organization_validation_service import (
    OrganizationValidationService,
)
from tables.services.rbac.permissions import IsSuperadmin


class OrganizationAdminViewSet(viewsets.ViewSet):
    """Superadmin-only management of Organizations.

    GET (list), POST (create), PATCH (rename), POST {id}/deactivate/,
    POST {id}/reactivate/.See docs/rbac/organization_management.md
    for the FE contract.

    Domain errors (404 not-found, 400 name-conflict, 400 last-active-org)
    are raised by the service layer as CustomAPIExeption subclasses and
    rendered through the project's `custom_exception_handler` envelope; the
    view layer does not catch or translate them.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, IsSuperadmin]
    lookup_value_regex = "[0-9]+"

    _service = OrganizationManagementService()
    _validator = OrganizationValidationService()

    @extend_schema(
        summary="List organizations (superadmin)",
        responses={200: OrganizationListResponseSerializer(many=True)},
    )
    def list(self, request):
        is_active = self._parse_is_active(request.query_params.get("is_active"))
        orgs = self._service.list_organizations_with_admins(is_active=is_active)
        return Response(
            OrganizationListResponseSerializer(
                orgs, many=True, context={"request": request}
            ).data
        )

    @extend_schema(
        summary="Create an organization (superadmin)",
        request=OrganizationCreateRequestSerializer,
        responses={
            201: OrganizationResponseSerializer,
            400: OpenApiResponse(description="Validation error or duplicate name"),
        },
    )
    def create(self, request):
        cleaned = self._validator.validate_create(request.data)
        org = self._service.create_organization(name=cleaned["name"])
        return Response(
            OrganizationResponseSerializer(org).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Rename an organization (superadmin)",
        request=OrganizationRenameRequestSerializer,
        responses={
            200: OrganizationResponseSerializer,
            400: OpenApiResponse(description="Validation error or duplicate name"),
            404: OpenApiResponse(description="Organization not found"),
        },
    )
    def partial_update(self, request, pk=None):
        cleaned = self._validator.validate_rename(request.data)
        org = self._service.rename_organization(org_id=int(pk), name=cleaned["name"])
        return Response(OrganizationResponseSerializer(org).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    @extend_schema(
        summary="Deactivate an organization (superadmin)",
        responses={
            200: OrganizationResponseSerializer,
            400: OpenApiResponse(
                description="Cannot deactivate the last active organization"
            ),
            404: OpenApiResponse(description="Organization not found"),
        },
    )
    def deactivate(self, request, pk=None):
        org = self._service.deactivate_organization(org_id=int(pk))
        return Response(OrganizationResponseSerializer(org).data)

    @action(detail=True, methods=["post"], url_path="reactivate")
    @extend_schema(
        summary="Reactivate an organization (superadmin)",
        responses={
            200: OrganizationResponseSerializer,
            404: OpenApiResponse(description="Organization not found"),
        },
    )
    def reactivate(self, request, pk=None):
        org = self._service.reactivate_organization(org_id=int(pk))
        return Response(OrganizationResponseSerializer(org).data)

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
