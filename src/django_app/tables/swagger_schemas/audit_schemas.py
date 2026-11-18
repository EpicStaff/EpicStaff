from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

AUDIT_TOKEN_CREATE = {
    "summary": "Mint a short-lived audit token for the active organization",
    "description": (
        "Mints a short-lived JWT scoped to the caller's "
        "active organization (`X-Organization-Id`), consumed directly by "
        "the `auditor` service — the frontend never calls Django again for "
        "audit reads/exports after this. Claims: `org_id`, `AUDIT` and "
        "`USER_AUDIT` (each lists only the actions the caller actually has — "
        "`read`/`export` — and may be empty), `retention_days` (from the org's "
        "`audit_retention_days` setting), `exp` (`AUDIT_TOKEN_TTL_SECONDS` after "
        "issue). Returns 403 before minting anything if the caller has neither "
        "AUDIT nor USER_AUDIT permission in the active org."
    ),
    "request": None,  # no request body - org comes from X-Organization-Id header
    "responses": {
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
            description="Caller has no AUDIT or USER_AUDIT read/export permission in the active organization.",
        ),
    },
}
