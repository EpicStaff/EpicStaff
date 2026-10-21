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
        200: OpenApiResponse(description="Import summary keyed by entity type."),
        403: FLOW_WITH_TRIGGER_NODES_403_RESPONSE,
    },
}
