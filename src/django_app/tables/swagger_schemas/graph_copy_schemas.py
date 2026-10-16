from drf_spectacular.utils import OpenApiResponse, inline_serializer
from rest_framework import serializers as drf_serializers

from tables.serializers.model_serializers import GraphLightSerializer
from tables.swagger_schemas.common_schemas import (
    FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
    UNAUTHORIZED_401_RESPONSE,
)

GRAPH_COPY_POST = {
    "summary": "Copy a flow",
    "description": (
        "Creates a duplicate of the flow identified by the id in the URL, in the active "
        "organization, with its nodes and edges. Requires CREATE on flows. A flow holding "
        "a trigger node (webhook, Telegram, schedule) also requires USE on flows: copied "
        "trigger nodes are live at once. Without it the response is 403 "
        "`flow_with_trigger_nodes_requires_use_permission` and nothing is written."
    ),
    "request": inline_serializer(
        name="GraphCopyRequest",
        fields={
            "name": drf_serializers.CharField(
                required=False,
                help_text=(
                    "Optional name for the copy. If omitted, the original's name is "
                    "reused with an auto-generated suffix on collision."
                ),
            ),
        },
    ),
    "responses": {
        201: OpenApiResponse(response=GraphLightSerializer, description="The new flow."),
        400: OpenApiResponse(description="The copy name raced with another copy; retry."),
        401: UNAUTHORIZED_401_RESPONSE,
        403: FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
        404: OpenApiResponse(description="No such flow in the active organization."),
    },
}
