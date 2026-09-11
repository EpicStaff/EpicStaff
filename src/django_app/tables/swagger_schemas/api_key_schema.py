"""OpenAPI schemas for the API key endpoints.

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/api_keys.md.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse

from tables.serializers.api_key_serializers import (
    ApiKeyAdminSerializer,
    ApiKeyCreateRequestSerializer,
    ApiKeyCreateResponseSerializer,
    ApiKeySerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_JWT_ONLY_403_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description="Key management requires a JWT session — API-key callers are rejected.",
    examples=[
        OpenApiExample(
            "API key caller",
            value={
                "status_code": 403,
                "code": "permission_denied",
                "message": (
                    "PermissionDenied: API keys cannot be used to manage API keys. "
                    "Authenticate with a user session (JWT)."
                ),
            },
            response_only=True,
            status_codes=["403"],
        ),
    ],
)

_NOT_FOUND_404_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description="Key does not exist in the caller's scope.",
    examples=[
        OpenApiExample(
            "Unknown key",
            value={
                "status_code": 404,
                "code": "api_key_not_found",
                "message": "ApiKeyNotFoundError: API key not found.",
            },
            response_only=True,
            status_codes=["404"],
        ),
    ],
)

PROFILE_API_KEYS_GET = dict(
    summary="List my API keys",
    description=(
        "Returns the caller's own API keys, newest first. Only metadata is "
        "returned — never the raw key or its hash. `status` is computed: "
        "active / expired / revoked."
    ),
    responses={
        200: ApiKeySerializer(many=True),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _JWT_ONLY_403_RESPONSE,
    },
)

PROFILE_API_KEYS_POST = dict(
    summary="Create an API key (raw key returned once)",
    description=(
        "Creates a personal API key. `expires_in_days`: omit for the 90-day "
        "default, send null for a non-expiring key. The raw key appears only "
        "in this response. At most 5 active keys per user."
    ),
    request=ApiKeyCreateRequestSerializer,
    responses={
        201: ApiKeyCreateResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Validation error or active-key limit reached.",
            examples=[
                OpenApiExample(
                    "Key limit reached",
                    value={
                        "status_code": 400,
                        "code": "api_key_limit_exceeded",
                        "message": (
                            "ApiKeyLimitExceededError: Maximum number of active API "
                            "keys reached (5). Revoke or delete an existing key first."
                        ),
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
                OpenApiExample(
                    "Validation error",
                    value={
                        "status_code": 400,
                        "code": "invalid",
                        "message": "FormValidationError: Validation failed",
                        "errors": [
                            {
                                "field": "expires_in_days",
                                "value": 0,
                                "reason": (
                                    "Must be null (no expiry) or an integer "
                                    "between 1 and 3650."
                                ),
                            }
                        ],
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _JWT_ONLY_403_RESPONSE,
    },
    examples=[
        OpenApiExample(
            "Default expiry (90 days)",
            value={"name": "my-mcp-client"},
            request_only=True,
        ),
        OpenApiExample(
            "Custom expiry",
            value={"name": "ci-pipeline", "expires_in_days": 30},
            request_only=True,
        ),
        OpenApiExample(
            "Never expires",
            value={"name": "long-lived-integration", "expires_in_days": None},
            request_only=True,
        ),
    ],
)

PROFILE_API_KEY_REVOKE_POST = dict(
    summary="Revoke my API key (kept for audit)",
    description=("Disables the key immediately; the record stays listed. Idempotent."),
    request=None,
    responses={
        200: ApiKeySerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: _JWT_ONLY_403_RESPONSE,
        404: _NOT_FOUND_404_RESPONSE,
    },
)

PROFILE_API_KEY_DELETE = dict(
    summary="Delete my API key",
    description="Permanently removes the key and its record.",
    responses={
        204: OpenApiResponse(description="Deleted"),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _JWT_ONLY_403_RESPONSE,
        404: _NOT_FOUND_404_RESPONSE,
    },
)

API_KEYS_MANAGEMENT_LIST = dict(
    summary="List members' API keys",
    description=(
        "Keys owned by members of every organization where the caller holds "
        "api_keys read. Superadmins see all. System keys never appear, and "
        "superadmin-owned keys are visible only to superadmins."
    ),
    parameters=[
        OpenApiParameter(
            name="org_ids",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Comma-separated organization ids to restrict the list to.",
        ),
        OpenApiParameter(
            name="user",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Filter by owner user id.",
        ),
        OpenApiParameter(
            name="status",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=["active", "expired", "revoked"],
            description="Filter by computed key status.",
        ),
        OpenApiParameter(
            name="search",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Case-insensitive match on key name or prefix.",
        ),
        OpenApiParameter(
            name="page",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="1-based page number.",
        ),
        OpenApiParameter(
            name="page_size",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
            description="Items per page (default 50, max 200).",
        ),
    ],
    responses={
        200: OpenApiResponse(description="Paginated API keys."),
        400: OpenApiResponse(
            description=(
                "Invalid `status` or `user` filter (invalid), or a malformed "
                "org_ids value (org_context_required)."
            )
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _JWT_ONLY_403_RESPONSE,
    },
)

API_KEYS_MANAGEMENT_REVOKE_POST = dict(
    summary="Revoke a member's API key",
    description=(
        "Requires api_keys delete in an organization the owner belongs to. "
        "Revocation disables the key in every organization the owner belongs to."
    ),
    request=None,
    responses={
        200: ApiKeyAdminSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: _JWT_ONLY_403_RESPONSE,
        404: _NOT_FOUND_404_RESPONSE,
    },
)

API_KEYS_MANAGEMENT_DELETE = dict(
    summary="Delete a member's API key",
    description=(
        "Requires api_keys delete in an organization the owner belongs to. "
        "Removes the record; revoke instead to keep it."
    ),
    responses={
        204: OpenApiResponse(description="Deleted"),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _JWT_ONLY_403_RESPONSE,
        404: _NOT_FOUND_404_RESPONSE,
    },
)
