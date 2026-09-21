"""OpenAPI schemas for the organization admin endpoints (/api/admin/organizations/).

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/organization_management.md. list / retrieve / partial_update are
permission-aware (ORGANIZATIONS bits); create / deactivate / reactivate /
destroy are platform-level and superadmin-only.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse

from tables.serializers.delete_serializers import DeleteReportSerializer
from tables.serializers.organization_serializers import (
    OrganizationCreateRequestSerializer,
    OrganizationListResponseSerializer,
    OrganizationRenameRequestSerializer,
    OrganizationResponseSerializer,
)

ORGANIZATIONS_LIST_GET = dict(
    summary="List organizations (permission-aware)",
    responses={200: OrganizationListResponseSerializer(many=True)},
)

ORGANIZATIONS_RETRIEVE_GET = dict(
    summary="Get one organization (settings surface)",
    responses={
        200: OrganizationResponseSerializer,
        404: OpenApiResponse(description="Organization not found or not accessible"),
    },
)

ORGANIZATIONS_CREATE_POST = dict(
    summary="Create an organization (superadmin)",
    request=OrganizationCreateRequestSerializer,
    responses={
        201: OrganizationResponseSerializer,
        400: OpenApiResponse(description="Validation error or duplicate name"),
    },
)

ORGANIZATIONS_UPDATE_PATCH = dict(
    summary="Rename an organization (ORGANIZATIONS.UPDATE or superadmin)",
    request=OrganizationRenameRequestSerializer,
    responses={
        200: OrganizationResponseSerializer,
        400: OpenApiResponse(description="Validation error or duplicate name"),
        404: OpenApiResponse(description="Organization not found or not accessible"),
    },
)

ORGANIZATIONS_DEACTIVATE_POST = dict(
    summary="Deactivate an organization (superadmin)",
    responses={
        200: OrganizationResponseSerializer,
        400: OpenApiResponse(description="Cannot deactivate the last active organization"),
        404: OpenApiResponse(description="Organization not found"),
    },
)

ORGANIZATIONS_REACTIVATE_POST = dict(
    summary="Reactivate an organization (superadmin)",
    responses={
        200: OrganizationResponseSerializer,
        404: OpenApiResponse(description="Organization not found"),
    },
)

ORGANIZATIONS_DESTROY_DELETE = dict(
    summary="Permanently delete an organization (superadmin)",
    parameters=[
        OpenApiParameter(
            name="dry_run",
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            description="When true, report what would be deleted and delete nothing.",
        )
    ],
    responses={
        200: DeleteReportSerializer,
        400: OpenApiResponse(
            description=(
                "default_organization_not_deletable, last_organization, "
                "or an invalid dry_run value"
            )
        ),
        404: OpenApiResponse(description="Organization not found"),
    },
)
