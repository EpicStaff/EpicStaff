from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

GRAPH_DELETE_BY_UUID_DELETE = {
    "summary": "Delete a graph by its UUID",
    "description": (
        "Deletes a single `Graph` looked up by its `uuid` field (as opposed to "
        "the numeric `pk` used by the standard destroy route), scoped to the "
        "active org. Routes through the model's normal `delete()` (soft-delete "
        "aware when `SOFT_DELETE` is enabled)."
    ),
    "responses": {
        204: OpenApiResponse(description="Graph deleted."),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="The `graph_uuid` path segment is not a valid UUID.",
            examples=[
                OpenApiExample(
                    "Invalid UUID",
                    value={"message": "Invalid graph UUID format"},
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description=(
                "No graph with that UUID exists in the active org (also "
                "returned for a graph belonging to another org, to avoid an "
                "existence leak)."
            ),
            examples=[
                OpenApiExample(
                    "Not found",
                    value={"message": "Provided graph does not exist"},
                    response_only=True,
                    status_codes=["404"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
    },
}
