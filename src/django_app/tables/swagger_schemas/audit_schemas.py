from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

AUDIT_TOKEN_CREATE = dict(
    summary="Mint a short-lived audit token for the active organization",
    description=(
        "Mints a 5-minute JWT scoped to the caller's "
        "active organization (`X-Organization-Id`), consumed directly by "
        "the `auditor` service — the frontend never calls Django again for "
        "audit reads/exports after this. Claims: `org_id`, `actions` "
        "(only the AUDIT actions the caller actually has — `read`/`export`), "
        "`retention_days` (from the org's `audit_retention_days` setting), "
        "`exp`. Returns 403 before minting anything if the caller has no "
        "AUDIT permission at all in the active org."
    ),
    request=None,  # no request body - org comes from X-Organization-Id header
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Token minted.",
            examples=[
                OpenApiExample(
                    "Token minted",
                    value={"token": "<jwt>", "expires_in": 300},
                    response_only=True,
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Caller has no AUDIT:READ or AUDIT:EXPORT in the active organization.",
        ),
    },
)
