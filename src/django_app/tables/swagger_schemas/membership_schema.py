"""OpenAPI schemas for the flat cross-org membership endpoints
(/api/admin/memberships/).

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/user_management.md. Org is data (in the body on create, derived
from the row on write) — these endpoints do NOT use the X-Organization-Id
header, and the list is cross-org.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse

from tables.serializers.membership_serializers import (
    MembershipCreateRequestSerializer,
    MembershipRoleUpdateRequestSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_FORBIDDEN_403 = OpenApiResponse(
    description=(
        "Caller lacks the required MEMBERSHIPS permission (permission_denied), a "
        "forbidden ?org_ids= entry, or an attempt to modify one's own "
        "membership (cannot_modify_self_membership)."
    )
)

_NOT_FOUND_404 = OpenApiResponse(
    description=(
        "Membership not found, or in an org the caller cannot access "
        "(membership_not_found — no existence leak)."
    )
)

MEMBERSHIPS_LIST_GET = dict(
    summary="List members across the caller's authorized orgs",
    description=(
        "Membership rows (one per user-in-org) from every org the caller can "
        "read members in. Filter with ?org_ids= (forbidden id → 403), "
        "?search= (email/display_name), ?role_id=, ?status=active|inactive, "
        "and ?ordering= (email/joined_at/role/org)."
    ),
    parameters=[
        OpenApiParameter(
            "org_ids",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Comma-separated org ids, e.g. `10,20`. Forbidden org → 403.",
        ),
        OpenApiParameter(
            "search",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Case-insensitive match on member email or display name.",
        ),
        OpenApiParameter(
            "role_id",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Exact role id (a built-in role id spans orgs).",
        ),
        OpenApiParameter(
            "status",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=["active", "inactive"],
            description="Filter by member account status.",
        ),
        OpenApiParameter(
            "ordering",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=[
                "email",
                "-email",
                "joined_at",
                "-joined_at",
                "role",
                "-role",
                "org",
                "-org",
            ],
            description="Sort field; prefix '-' for descending. Default: org, then email.",
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
    responses={
        200: OpenApiResponse(description="Paginated membership rows."),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _FORBIDDEN_403,
    },
)

MEMBERSHIPS_CREATE_POST = dict(
    summary="Add an existing user to an organization",
    description=(
        "Links an EXISTING account to `org_id` with `role_id`. Provide exactly "
        "one of `email` or `user_id`. Account creation stays a superadmin-only "
        "operation on /api/admin/users/. Requires MEMBERSHIPS create in the target org."
    ),
    request=MembershipCreateRequestSerializer,
    responses={
        201: OpenApiResponse(description="The created membership row."),
        400: OpenApiResponse(
            description="Validation error, already a member "
            "(membership_already_exists), or non-assignable role."
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _FORBIDDEN_403,
        404: OpenApiResponse(
            description="Unknown account (user_not_found) or org "
            "the caller cannot access."
        ),
    },
)

MEMBERSHIPS_UPDATE_PATCH = dict(
    summary="Change a member's role",
    description=(
        "Assigns `role_id` to the membership. Any existing assignable role may "
        "be assigned to others; a non-superadmin cannot change their own "
        "membership. Requires MEMBERSHIPS update in the row's org."
    ),
    request=MembershipRoleUpdateRequestSerializer,
    responses={
        200: OpenApiResponse(description="The updated membership row."),
        400: OpenApiResponse(description="Validation error or non-assignable role."),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _FORBIDDEN_403,
        404: _NOT_FOUND_404,
    },
)

MEMBERSHIPS_DESTROY_DELETE = dict(
    summary="Remove a member from an organization",
    description=(
        "Deletes the membership row (the user account stays). A non-superadmin "
        "cannot remove their own membership. Requires MEMBERSHIPS delete in the "
        "row's org."
    ),
    responses={
        204: OpenApiResponse(description="Removed"),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _FORBIDDEN_403,
        404: _NOT_FOUND_404,
    },
)

MEMBERSHIPS_ASSIGNABLE_USERS_GET = dict(
    summary="List accounts that can be added to an organization",
    description=(
        "Candidates for POST /api/admin/memberships/: active, non-superadmin "
        "accounts visible to the caller through an org where they can read "
        "members. Each row carries `org_ids` — where that account already "
        "belongs, limited to the caller's readable orgs. Requires MEMBERSHIPS "
        "create in at least one org."
    ),
    parameters=[
        OpenApiParameter(
            "search",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Case-insensitive match on email or display name.",
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
    responses={
        200: OpenApiResponse(description="Paginated candidate accounts."),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _FORBIDDEN_403,
    },
)
