"""OpenAPI schemas for the user-account admin endpoints (/api/admin/users/).

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/user_management.md. The endpoints are superadmin-only and do NOT
use the X-Organization-Id header — organization is a query filter
(`?org_ids=`) resolved through the accounts' memberships.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse

from tables.serializers.delete_serializers import DeleteReportSerializer
from tables.serializers.user_management_serializers import (
    UserCreateRequestSerializer,
    UserResponseSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

USERS_LIST_GET = {
    "summary": "List user accounts (superadmin)",
    "description": (
        "Global account entity, paginated. Filter with ?org_ids= (accounts "
        "holding a membership in any of those orgs), ?search= "
        "(email/display name), ?status=active|inactive, ?role_id= (held in "
        "any in-scope org), ?is_superadmin=, and ?ordering=. Each row carries "
        "the account's full memberships[], unaffected by the filters."
    ),
    "parameters": [
        OpenApiParameter(
            "org_ids",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                "Comma-separated org ids, e.g. `10,20`. Accounts with no "
                "membership in them are excluded, superadmins included."
            ),
        ),
        OpenApiParameter(
            "search",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Case-insensitive match on email or display name.",
        ),
        OpenApiParameter(
            "status",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=["active", "inactive"],
            description="Filter by account status.",
        ),
        OpenApiParameter(
            "role_id",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                "Exact role id held in at least one org in scope (a built-in role id spans orgs)."
            ),
        ),
        OpenApiParameter(
            "is_superadmin",
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Filter by the global superadmin flag.",
        ),
        OpenApiParameter(
            "ordering",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=[
                "email",
                "-email",
                "created_at",
                "-created_at",
                "display_name",
                "-display_name",
            ],
            description=(
                "Sort field; prefix '-' for descending. Default: newest account first, then email."
            ),
        ),
        OpenApiParameter(
            "page",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="1-based page number.",
        ),
        OpenApiParameter(
            "page_size",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Items per page (default 50, max 200).",
        ),
    ],
    "responses": {
        200: UserResponseSerializer(many=True),
        400: OpenApiResponse(
            description=(
                "Malformed org_ids (org_context_required), or an invalid "
                "status / role_id / is_superadmin value (invalid)."
            )
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(description="Caller is not a superadmin."),
    },
)

USERS_CREATE_POST = dict(
    summary="Create a user (superadmin)",
    request=UserCreateRequestSerializer,
    responses={
        201: UserResponseSerializer,
        400: OpenApiResponse(description="Validation error or duplicate email"),
        404: OpenApiResponse(description="Organization or role not found"),
    },
)

USERS_GRANT_SUPERADMIN_POST = dict(
    summary="Grant superadmin (superadmin)",
    responses={
        200: UserResponseSerializer,
        404: OpenApiResponse(description="User not found"),
    },
)

USERS_REVOKE_SUPERADMIN_POST = dict(
    summary="Revoke superadmin (superadmin)",
    responses={
        200: UserResponseSerializer,
        400: OpenApiResponse(description="Cannot revoke last superadmin"),
        404: OpenApiResponse(description="User not found"),
    },
)

USERS_DEACTIVATE_POST = dict(
    summary="Deactivate a user account (superadmin)",
    responses={
        200: UserResponseSerializer,
        400: OpenApiResponse(description="Cannot deactivate the last active superadmin"),
        404: OpenApiResponse(description="User not found"),
    },
)

USERS_REACTIVATE_POST = dict(
    summary="Reactivate a user account (superadmin)",
    responses={
        200: UserResponseSerializer,
        404: OpenApiResponse(description="User not found"),
    },
)

USERS_DESTROY_DELETE = dict(
    summary="Permanently delete a user (superadmin)",
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
                "cannot_delete_self, last_superadmin, or an invalid dry_run value"
            )
        ),
        404: OpenApiResponse(description="User not found"),
    },
)
