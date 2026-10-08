"""OpenAPI 403 pieces shared by the /api/admin/* governance endpoints.

The API-key rejections come from `RestrictApiKeyToUserKeyReads`, which runs
first on every admin action. The examples read the gate's own messages, so
the documented body cannot drift from what the gate returns.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from rbac.access.gates import RestrictApiKeyToUserKeyReads


def permission_denied_example(name: str, message: str) -> OpenApiExample:
    """Return a 403 `permission_denied` envelope example carrying `message`."""
    return OpenApiExample(
        name,
        value={"status_code": 403, "code": "permission_denied", "message": message},
        response_only=True,
        status_codes=["403"],
    )


SYSTEM_KEY_REJECTED_EXAMPLE = permission_denied_example(
    "System API key", RestrictApiKeyToUserKeyReads.non_user_key_message
)
API_KEY_WRITE_REJECTED_EXAMPLE = permission_denied_example(
    "API key on a write", RestrictApiKeyToUserKeyReads.write_message
)


def admin_read_forbidden_403(description: str) -> OpenApiResponse:
    """403 for an admin read: `description` plus the SYSTEM-key rejection."""
    return OpenApiResponse(
        response=OpenApiTypes.OBJECT,
        description=(
            f"{description} The system API key is rejected outright "
            "(permission_denied); a USER key reads with its owner's permissions."
        ),
        examples=[SYSTEM_KEY_REJECTED_EXAMPLE],
    )


def admin_write_forbidden_403(description: str) -> OpenApiResponse:
    """403 for an admin write: `description` plus both API-key rejections."""
    return OpenApiResponse(
        response=OpenApiTypes.OBJECT,
        description=(
            f"{description} Writes are JWT-only: any API key is rejected "
            "(permission_denied), the system key with its own message."
        ),
        examples=[API_KEY_WRITE_REJECTED_EXAMPLE, SYSTEM_KEY_REJECTED_EXAMPLE],
    )
