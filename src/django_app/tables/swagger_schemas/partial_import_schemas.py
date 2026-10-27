from drf_spectacular.utils import OpenApiResponse

from tables.swagger_schemas.common_schemas import FLOW_WITH_TRIGGER_NODES_403_RESPONSE

PARTIAL_IMPORT_SWAGGER = {
    "request": {
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary"},
            },
            "required": ["file"],
        }
    },
    "responses": {
        200: OpenApiResponse(
            description=(
                "`content`: the file's nodes and edges in the `GET /graphs/{id}/` shape, NOT written "
                "to the flow (the client adds them and the flow save persists them). "
                "`summary`: dependencies keyed by entity type."
            )
        ),
        403: FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
    },
}
