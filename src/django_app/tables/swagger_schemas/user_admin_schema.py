"""OpenAPI schema for the user-account admin list (/api/admin/users/).

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/user_management.md. The endpoint is superadmin-only and does NOT
use the X-Organization-Id header — organization is a query filter
(`?org_ids=`) resolved through the accounts' memberships.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse

from tables.serializers.user_management_serializers import UserResponseSerializer
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
}
