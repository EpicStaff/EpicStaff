from drf_spectacular.utils import OpenApiResponse

from tables.serializers.graph_view_settings_serializers import GraphViewSettingsSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_PERSONAL_NOTE = (
    "The caller's own flow-editor settings and default timezone for this flow, over their "
    "account preferences. "
    "Other users never see them, and they are not copied or exported with the flow. Needs "
    "only READ on flows, for every method: they change how the caller sees the flow, never "
    "the flow."
)

_403_RESPONSE = OpenApiResponse(
    description=(
        "No READ on flows in the active organization, or an API key or plugin credential: "
        "view settings change only from a user session."
    )
)
_404_RESPONSE = OpenApiResponse(
    description="No such flow in the active organization, or the flow is in the recycle bin."
)

GRAPH_VIEW_SETTINGS_GET = {
    "summary": "Get my view settings for a flow",
    "description": f"{_PERSONAL_NOTE} `settings` is empty when the caller has none.",
    "responses": {
        200: GraphViewSettingsSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        403: _403_RESPONSE,
        404: _404_RESPONSE,
    },
}

GRAPH_VIEW_SETTINGS_PUT = {
    "summary": "Replace my view settings for a flow",
    "description": (
        f"{_PERSONAL_NOTE} Replaces the whole value. `settings` takes the keys of the "
        "flow_editor preference section and `default_timezone`, an IANA zone name that "
        "overrides the account's `general.default_timezone` for new schedule triggers in "
        "this flow (leave it out to follow the account; null is rejected). An unknown key "
        "or an invalid value is rejected."
    ),
    "request": GraphViewSettingsSerializer,
    "responses": {
        200: GraphViewSettingsSerializer,
        400: OpenApiResponse(
            description=(
                "An unknown key or an invalid value in `settings`, such as an unknown or "
                "null `default_timezone`."
            )
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _403_RESPONSE,
        404: _404_RESPONSE,
    },
}

GRAPH_VIEW_SETTINGS_DELETE = {
    "summary": "Drop my view settings for a flow",
    "description": f"{_PERSONAL_NOTE} The flow then follows the caller's account preferences.",
    "responses": {
        204: OpenApiResponse(description="Dropped, or there were none."),
        401: UNAUTHORIZED_401_RESPONSE,
        403: _403_RESPONSE,
        404: _404_RESPONSE,
    },
}
