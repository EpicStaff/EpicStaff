"""OpenAPI schemas for the organization admin endpoints (/api/admin/organizations/).

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/organization_management.md. list / retrieve / partial_update are
permission-aware (ORGANIZATIONS bits); create / deactivate / reactivate /
destroy are platform-level and superadmin-only.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from tables.serializers.delete_serializers import OrganizationDeleteReportSerializer

from rbac.serializers.organizations import (
    OrganizationCreateRequestSerializer,
    OrganizationListResponseSerializer,
    OrganizationRenameRequestSerializer,
    OrganizationResponseSerializer,
)

ORGANIZATIONS_LIST_GET = {
    "summary": "List organizations (permission-aware)",
    "responses": {200: OrganizationListResponseSerializer(many=True)},
}

ORGANIZATIONS_RETRIEVE_GET = {
    "summary": "Get one organization (settings surface)",
    "responses": {
        200: OrganizationResponseSerializer,
        404: OpenApiResponse(description="Organization not found or not accessible"),
    },
}

ORGANIZATIONS_CREATE_POST = {
    "summary": "Create an organization (superadmin)",
    "request": OrganizationCreateRequestSerializer,
    "responses": {
        201: OrganizationResponseSerializer,
        400: OpenApiResponse(description="Validation error or duplicate name"),
    },
}

ORGANIZATIONS_UPDATE_PATCH = {
    "summary": "Rename an organization (ORGANIZATIONS.UPDATE or superadmin)",
    "request": OrganizationRenameRequestSerializer,
    "responses": {
        200: OrganizationResponseSerializer,
        400: OpenApiResponse(description="Validation error or duplicate name"),
        404: OpenApiResponse(description="Organization not found or not accessible"),
    },
}

ORGANIZATIONS_DEACTIVATE_POST = {
    "summary": "Deactivate an organization (superadmin)",
    "responses": {
        200: OrganizationResponseSerializer,
        400: OpenApiResponse(description="Cannot deactivate the last active organization"),
        404: OpenApiResponse(description="Organization not found"),
    },
}

ORGANIZATIONS_REACTIVATE_POST = {
    "summary": "Reactivate an organization (superadmin)",
    "responses": {
        200: OrganizationResponseSerializer,
        404: OpenApiResponse(description="Organization not found"),
    },
}

ORGANIZATIONS_DESTROY_DELETE = {
    "summary": "Permanently delete an organization (superadmin) — or preview with ?dry_run=true",
    "parameters": [
        OpenApiParameter(
            name="dry_run",
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            description="If true, report what would be deleted and delete nothing.",
        )
    ],
    "responses": {
        200: OrganizationDeleteReportSerializer,
        400: OpenApiResponse(
            description="default_organization_not_deletable or last_organization"
        ),
        404: OpenApiResponse(description="Organization not found"),
    },
}
