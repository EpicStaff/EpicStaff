from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from tables.serializers.knowledge_serializers import (
    SourceCollectionDetailSerializer,
    SourceCollectionListSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

SOURCE_COLLECTIONS_GET = {
    "summary": "List all source collections.",
    "description": "List all source collections for the user.\n\nURL: GET /source-collections/",
    "responses": {
        200: SourceCollectionListSerializer(many=True),
        401: UNAUTHORIZED_401_RESPONSE,
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to retrieve collections: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_GET = {
    "summary": "Retrieve a specific source collection.",
    "description": "Retrieve a specific source collection by ID.\n\nURL: GET /source-collections/{id}/",
    "responses": {
        200: SourceCollectionDetailSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
            examples=[
                OpenApiExample(
                    name="Not Found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to retrieve collection: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_POST = {
    "summary": "Create a new empty source collection.",
    "description": "Create a new empty source collection.\n\nURL: POST /source-collections/",
    "responses": {
        201: SourceCollectionDetailSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to create collection: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_PATCH = {
    "summary": "Partially update collection name.",
    "description": "Update the collection name.\n\nURL: PATCH /source-collections/{id}/",
    "responses": {
        200: SourceCollectionDetailSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
            examples=[
                OpenApiExample(
                    name="Not Found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to update collection: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_PUT = {
    "summary": "Full update of collection name.",
    "description": "Full update of the collection name (same as partial update).\n\nURL: PUT /source-collections/{id}/",
    "responses": {
        200: SourceCollectionDetailSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
            examples=[
                OpenApiExample(
                    name="Not Found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to update collection: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_DELETE = {
    "summary": "Delete a source collection.",
    "description": "Delete collection and all its documents. Cleans up unreferenced DocumentContent automatically.\n\nURL: DELETE /source-collections/{id}/",
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection deleted successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "Collection deleted successfully",
                        "deleted_count": 1,
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
            examples=[
                OpenApiExample(
                    name="Not Found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to delete collection: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_BULK_DELETE_POST = {
    "summary": "Bulk delete source collections.",
    "description": "Bulk delete collections with automatic unreferenced content cleanup.\n\nURL: POST /source-collections/bulk-delete/",
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collections deleted successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "Successfully deleted 3 collection(s)",
                        "deleted_count": 3,
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Bad request — missing or invalid collection_ids.",
            examples=[
                OpenApiExample(
                    name="Missing collection_ids",
                    value={"error": "collection_ids is required and must be a non-empty list"},
                    response_only=True,
                    status_codes=["400"],
                ),
                OpenApiExample(
                    name="Invalid collection_ids type",
                    value={"error": "collection_ids must be a list"},
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to delete collections: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_COPY_POST = {
    "summary": "Copy a source collection.",
    "description": "Copy collection without duplicating binary content. New metadata records point to same DocumentContent.\n\nURL: POST /api/source-collections/{id}/copy/",
    "responses": {
        201: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection copied successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "Collection copied successfully",
                        "collection": {
                            "collection_id": 2,
                            "collection_name": "My Copy",
                            "user_id": 1,
                            "status": "active",
                            "document_count": 5,
                            "rag_configurations": [],
                            "created_at": "2024-01-02T00:00:00Z",
                            "updated_at": "2024-01-02T00:00:00Z",
                        },
                    },
                    response_only=True,
                    status_codes=["201"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Source collection not found.",
            examples=[
                OpenApiExample(
                    name="Not Found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to copy collection: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}

SOURCE_COLLECTION_AVAILABLE_RAGS_GET = {
    "summary": "Get available RAG configurations for a collection.",
    "description": "Get all RAG configurations available for this collection.\n\nURL: GET /source-collections/{id}/available-rags/\n\nQuery params:\n- status: Filter by status (comma-separated). Example: ?status=completed,warning\n  If not provided, defaults to 'completed,warning,new'",
    "responses": {
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="List of available RAG configurations.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value=[
                        {
                            "rag_id": 9,
                            "rag_type": "naive",
                            "rag_status": "completed",
                            "collection_id": 29,
                            "created_at": "2025-12-17T14:17:01.594229Z",
                            "updated_at": "2025-12-17T15:30:00Z",
                        },
                        {
                            "rag_id": 12,
                            "rag_type": "graph",
                            "rag_status": "warning",
                            "collection_id": 29,
                            "created_at": "2025-12-18T09:00:00Z",
                            "updated_at": "2025-12-18T10:00:00Z",
                        },
                    ],
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
            examples=[
                OpenApiExample(
                    name="Not Found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Internal server error.",
            examples=[
                OpenApiExample(
                    name="Internal Server Error",
                    value={"error": "Failed to fetch available RAGs: <error details>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
}
