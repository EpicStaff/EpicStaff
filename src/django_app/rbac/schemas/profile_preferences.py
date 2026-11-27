"""OpenAPI schemas for the personal preferences endpoint."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

from rbac.access.gates import DenyApiKeyAuth
from rbac.profile.preferences.sections import PREFERENCE_SECTIONS
from rbac.schemas.admin_surface import permission_denied_example

PROFILE_PREFERENCES_SECTION_PATCH = {
    "summary": "Change one section of my preferences",
    "description": (
        "Merges the sent keys into the section; keys left out keep their values. The "
        "section's keys, types and defaults are those of the same section in `preferences` "
        "of `GET /api/profile/`. A key the section does not define is rejected. The response "
        "is the whole section after the change. A personal UI choice: no user action is "
        "recorded. `X-Organization-Id` is optional. It is read only when the body changes a "
        "preference that holds an organization's object; otherwise it is ignored, even when "
        "it names an organization the caller left or one that was deactivated."
    ),
    "parameters": [
        OpenApiParameter(
            "section",
            OpenApiTypes.STR,
            OpenApiParameter.PATH,
            enum=list(PREFERENCE_SECTIONS),
        )
    ],
    "request": OpenApiTypes.OBJECT,
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="The section, the stored values over the defaults.",
        ),
        400: OpenApiResponse(
            description=(
                "An unknown key or an invalid value, or an organization-keyed preference "
                "changed without a valid `X-Organization-Id` (`org_context_required`)."
            )
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description=(
                "An API key or plugin credential: preferences change only from a user "
                "session. Also, when the body changes an organization-keyed preference, a "
                "named organization the caller may not act in."
            ),
            examples=[permission_denied_example("API key caller", DenyApiKeyAuth.message)],
        ),
        404: OpenApiResponse(
            description=(
                "No such section (`preference_section_not_found`), or a superadmin's "
                "organization-keyed change naming an organization that does not exist."
            )
        ),
    },
}
