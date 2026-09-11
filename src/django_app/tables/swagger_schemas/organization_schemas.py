from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from tables.serializers.organization_serializers import (
    OrganizationResponseSerializer,
    OrganizationSettingsUpdateSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

ORGANIZATION_SETTINGS_UPDATE = dict(
    summary="Update settings for the caller's own organization",
    description=(
        "Update org-level settings for the active organization "
        "(resolved from `X-Organization-Id`, not a URL id — self-service, "
        "not the superadmin org CRUD surface). Currently exposes only "
        "`audit_retention_days` (0 = unlimited, the default). Gated on "
        "ORGANIZATIONS:update, not AUDIT permissions — retention is a "
        "general org setting, not audit data itself."
    ),
    request=OrganizationSettingsUpdateSerializer,
    responses={
        200: OrganizationResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Validation error — audit_retention_days missing or negative.",
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Caller lacks ORGANIZATIONS:update in the active organization.",
        ),
    },
)
