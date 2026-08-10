"""OpenAPI schemas for the role-admin endpoints (/api/admin/roles/).

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/roles_and_permissions.md. These endpoints do NOT use the
X-Organization-Id header — the org is data (in the body on create,
derived from the row on read/update/delete) and the list is cross-org.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
)

from tables.serializers.permission_serializers import RoleResponseSerializer
from tables.serializers.role_admin_serializers import (
    RoleDeletePreviewSerializer,
    RoleDeleteResultSerializer,
    RoleListResponseSerializer,
    RoleWriteSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_FORBIDDEN_403 = OpenApiResponse(
    description=(
        "Caller lacks the required ROLES permission (permission_denied), or "
        "?org_ids= named an org the caller cannot read."
    )
)

_WRITE_FORBIDDEN_403 = OpenApiResponse(
    description=(
        "permission_denied (no ROLES permission in the role's org), "
        "permission_escalation_denied (granting a bit the caller doesn't "
        "hold), or built_in_role_immutable (target is a built-in role)."
    )
)

_NOT_FOUND_404 = OpenApiResponse(
    description=(
        "Role not found, or a custom role in an org the caller cannot read "
        "(role_not_found — no existence leak)."
    )
)

_NAME_CONFLICT_400 = OpenApiResponse(
    description=(
        "Validation error, or a role with this name already exists in the "
        "org (role_name_conflict)."
    )
)

ROLES_LIST_GET = dict(
    summary="List roles across the caller's authorized orgs",
    description=(
        "Built-in templates (once, in `built_in_roles`) plus custom roles "
        "(`results`, paginated) from every org the caller can read. Filter "
        "with ?org_ids=; omit for all readable orgs."
    ),
    parameters=[
        OpenApiParameter(
            name="org_ids",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.STR,
            required=False,
            description=(
                "Comma-separated org ids to include, e.g. `10,20`. A "
                "forbidden org → 403. Omit for every org the caller can read."
            ),
        ),
        OpenApiParameter(
            name="page",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.INT,
            required=False,
            description="Page number for the paginated `results`.",
        ),
        OpenApiParameter(
            name="page_size",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.INT,
            required=False,
            description="Items per page (default 50, max 200).",
        ),
    ],
    responses={
        200: RoleListResponseSerializer,
        400: OpenApiResponse(description="Malformed org_ids (org_context_required)."),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _FORBIDDEN_403,
    },
)

ROLES_RETRIEVE_GET = dict(
    summary="Single role with its full permission matrix",
    responses={
        200: RoleResponseSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: _FORBIDDEN_403,
        404: _NOT_FOUND_404,
    },
)

ROLES_CREATE_POST = dict(
    summary="Create a custom role in an organization",
    description=(
        "Creates an org-scoped custom role (org_id in the body). Requires "
        "ROLES create in that org; the caller can only grant permissions "
        "they themselves hold (ceiling rule). An empty `permissions` list "
        "is a valid 'no access' role."
    ),
    request=RoleWriteSerializer,
    responses={
        201: RoleResponseSerializer,
        400: _NAME_CONFLICT_400,
        401: UNAUTHORIZED_401_RESPONSE,
        403: _WRITE_FORBIDDEN_403,
    },
    examples=[
        OpenApiExample(
            "Billing Manager",
            value={
                "org_id": 10,
                "name": "Billing Manager",
                "description": "Manage billing secrets",
                "permissions": [
                    {"resource_type": "secrets", "actions": ["read", "update"]}
                ],
            },
            request_only=True,
        ),
        OpenApiExample(
            "No-access role",
            value={"org_id": 10, "name": "No Access", "permissions": []},
            request_only=True,
        ),
    ],
)

ROLES_UPDATE_PATCH = dict(
    summary="Edit a custom role (name / description / permissions)",
    description=(
        "Partial update. If `permissions` is sent it fully replaces the "
        "role's matrix. Built-in roles are immutable; the ceiling rule "
        "applies to added bits. Changes take effect for assignees on their "
        "next request."
    ),
    request=RoleWriteSerializer,
    responses={
        200: RoleResponseSerializer,
        400: _NAME_CONFLICT_400,
        401: UNAUTHORIZED_401_RESPONSE,
        403: _WRITE_FORBIDDEN_403,
        404: _NOT_FOUND_404,
    },
    examples=[
        OpenApiExample(
            "Rename + narrow permissions",
            value={
                "name": "Billing L2",
                "permissions": [{"resource_type": "secrets", "actions": ["read"]}],
            },
            request_only=True,
        ),
    ],
)

ROLES_DESTROY_DELETE = dict(
    summary="Delete a custom role — or preview with ?dry_run=true",
    description=(
        "Deletes a custom role and reassigns its members to the built-in "
        "Member role (never evicts them). With ?dry_run=true nothing is "
        "deleted and the affected members are returned so the UI can warn "
        "first. Built-in roles are immutable."
    ),
    parameters=[
        OpenApiParameter(
            name="dry_run",
            location=OpenApiParameter.QUERY,
            type=OpenApiTypes.BOOL,
            required=False,
            description=(
                "If true, return the members that would be reassigned and "
                "delete nothing."
            ),
        ),
    ],
    responses={
        200: PolymorphicProxySerializer(
            component_name="RoleDeleteOrPreview",
            serializers=[RoleDeleteResultSerializer, RoleDeletePreviewSerializer],
            resource_type_field_name=None,
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _WRITE_FORBIDDEN_403,
        404: _NOT_FOUND_404,
    },
    examples=[
        OpenApiExample(
            "Deleted",
            value={"reassigned_count": 5},
            response_only=True,
            status_codes=["200"],
        ),
        OpenApiExample(
            "Dry-run preview",
            value={
                "role_id": 101,
                "assigned_count": 5,
                "affected_users": [
                    {"user_id": 42, "email": "ann@example.com", "display_name": "Ann"}
                ],
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
