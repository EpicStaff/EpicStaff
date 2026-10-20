"""OpenAPI schemas for /api/admin/organizations/{id}/retention/."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

from rbac.serializers.organization_retention import (
    OrganizationRetentionResponseSerializer,
    OrganizationRetentionUpdateRequestSerializer,
)

_DENIED_403_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description="Caller can see the organization but lacks the ORGANIZATIONS permission needed.",
)
_NOT_FOUND_404_RESPONSE = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description="Organization not found or not accessible.",
)

ORGANIZATION_RETENTION_GET = {
    "summary": "Get an organization's data retention (ORGANIZATIONS.READ or superadmin)",
    "description": (
        "Per data type: the organization's chosen days (`null` = instance default), the "
        "days actually applied (`*_effective_days`, 0 = keep forever), and the instance "
        "`retention_policy` bounding the choices. An organization that never changed its "
        "retention returns nulls and null `updated_at` / `updated_by`."
    ),
    "responses": {
        200: OrganizationRetentionResponseSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: _DENIED_403_RESPONSE,
        404: _NOT_FOUND_404_RESPONSE,
    },
}

ORGANIZATION_RETENTION_PATCH = {
    "summary": "Change an organization's data retention (ORGANIZATIONS.UPDATE or superadmin)",
    "description": (
        "Send any subset of `sessions_days`, `conversations_days`, `audit_days`; at least "
        "one is required. Each must be one of `retention_policy.<type>.allowed`, `null` "
        "to fall back to the instance default, or the value already stored (so a form "
        "stays savable after a cap is lowered). Unsent types are left unchanged."
    ),
    "request": OrganizationRetentionUpdateRequestSerializer,
    "responses": {
        200: OrganizationRetentionResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description=(
                "FormValidationError: `errors` lists each rejected field as "
                "{field, value, reason}. Sent when no retention field is present, or a "
                "value is not null, not in the allowed list and not the stored value."
            ),
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _DENIED_403_RESPONSE,
        404: _NOT_FOUND_404_RESPONSE,
    },
}
