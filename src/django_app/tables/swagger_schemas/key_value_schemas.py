from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

KEY_VALUE_TABLE_USAGE_GET = {
    "summary": "Key-Value table usage",
    "description": (
        "How many Key-Value nodes reference this table, and in how many distinct flows. "
        "Nodes of soft-deleted flows are not counted. Deleting the table is allowed while "
        "it is in use: its nodes stay in their flows with no table selected."
    ),
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Node and flow counts",
            examples=[
                OpenApiExample(
                    "Used by three nodes in two flows",
                    value={"node_count": 3, "flow_count": 2},
                ),
                OpenApiExample("Unused", value={"node_count": 0, "flow_count": 0}),
            ],
        ),
        404: OpenApiResponse(description="No such table in the active organization"),
    },
}
