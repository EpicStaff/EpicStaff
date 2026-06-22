from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse
from tables.serializers.naive_rag_serializers import (
    ChunkPreviewResponseSerializer,
    ChunkingResponseSerializer,
)
from tables.serializers.serializers import ProcessRagIndexingSerializer
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

NAIVE_RAG_DOCUMENT_CONFIGS_GET = dict(
    summary="List document statuses inside a NaiveRag",
    description=(
        "List document configs attached to this NaiveRag with their current "
        "indexing status, chunk parameters and the latest error (if any).\n\n"
        "Pass `?ids=10,11,42` to fetch a subset — useful when polling only the "
        "documents you just submitted to `/api/process-rag-indexing/`. IDs that "
        "don't belong to this NaiveRag are silently dropped.\n\n"
        "URL: GET /api/naive-rag/{naive_rag_id}/document-configs/[?ids=10,11,42]"
    ),
    parameters=[
        OpenApiParameter(
            name="ids",
            location=OpenApiParameter.QUERY,
            description=(
                "Comma-separated naive_rag_document_id whitelist. Omit for all."
            ),
            required=False,
            type=str,
        ),
    ],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document configs retrieved successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "naive_rag_id": 1,
                        "total_configs": 2,
                        "configs": [
                            {
                                "naive_rag_document_id": 1,
                                "document_id": 10,
                                "file_name": "report.pdf",
                                "chunk_strategy": "fixed",
                                "chunk_size": 512,
                                "chunk_overlap": 50,
                                "additional_params": {},
                                "status": "processed",
                                "total_chunks": 20,
                                "total_embeddings": 20,
                                "created_at": "2024-01-01T00:00:00Z",
                                "processed_at": "2024-01-01T00:01:00Z",
                            },
                            {
                                "naive_rag_document_id": 2,
                                "document_id": 11,
                                "file_name": "notes.docx",
                                "chunk_strategy": "fixed",
                                "chunk_size": 512,
                                "chunk_overlap": 50,
                                "additional_params": {},
                                "status": "pending",
                                "total_chunks": 0,
                                "total_embeddings": 0,
                                "created_at": "2024-01-02T00:00:00Z",
                                "processed_at": None,
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag not found.",
            examples=[
                OpenApiExample(
                    name="NaiveRag not found",
                    value={"error": "NaiveRag not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIGS_CHUNK_GET = dict(
    summary="Get chunks for a document config (preview or indexed)",
    description=(
        "Get chunks for a document config.\n\n"
        "URL: GET /naive-rag/{naive_rag_id}/document-configs/{document_config_id}/chunks/\n\n"
        "Returns:\n"
        "- Preview chunks if status is CHUNKED (not yet indexed)\n"
        "- Indexed chunks if status is COMPLETED\n\n"
        "Supports pagination for endless scrolling via `limit` and `offset` query parameters."
    ),
    responses={
        200: ChunkPreviewResponseSerializer,
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid query parameters.",
            examples=[
                OpenApiExample(
                    name="Invalid parameters",
                    value={"error": "limit and offset must be integers"},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag or DocumentConfig not found.",
            examples=[
                OpenApiExample(
                    name="DocumentConfig not found",
                    value={"error": "DocumentConfig 5 not found for NaiveRag 1"},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIG_GET = dict(
    summary="Get single document config",
    description="Get single document config.\n\nURL: GET /api/naive-rag/{naive_rag_id}/document-configs/{pk}/",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document config retrieved successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "naive_rag_document_id": 1,
                        "document_id": 10,
                        "file_name": "report.pdf",
                        "chunk_strategy": "fixed",
                        "chunk_size": 512,
                        "chunk_overlap": 50,
                        "additional_params": {},
                        "status": "processed",
                        "total_chunks": 20,
                        "total_embeddings": 20,
                        "created_at": "2024-01-01T00:00:00Z",
                        "processed_at": "2024-01-01T00:01:00Z",
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document config not found.",
            examples=[
                OpenApiExample(
                    name="Not found",
                    value={
                        "error": "Document config [1] for naive_rag_id [2] not found"
                    },
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIG_PUT = dict(
    summary="Update single document config",
    description="Update single document config.\n\nURL: PUT /api/naive-rag/{naive_rag_id}/document-configs/{pk}/",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document config updated successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "Document config updated successfully",
                        "config": {
                            "naive_rag_document_id": 1,
                            "document_id": 10,
                            "file_name": "report.pdf",
                            "chunk_strategy": "character",
                            "chunk_size": 1500,
                            "chunk_overlap": 200,
                            "additional_params": {},
                            "status": "processed",
                            "total_chunks": 20,
                            "total_embeddings": 20,
                            "created_at": "2024-01-01T00:00:00Z",
                            "processed_at": "2024-01-01T00:01:00Z",
                        },
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid chunk parameters.",
            examples=[
                OpenApiExample(
                    name="Invalid parameters",
                    value={"errors": {"chunk_size": ["This field is required."]}},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document config not found.",
            examples=[
                OpenApiExample(
                    name="Not found",
                    value={
                        "error": "Document config [1] for naive_rag_id [2] not found"
                    },
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIG_DELETE = dict(
    summary="Delete a single document config",
    description="Delete a single document config.\n\nURL: DELETE /api/naive-rag/{naive_rag_id}/document-configs/{pk}/",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document config deleted successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "Document config deleted successfully",
                        "config_id": 1,
                        "document_name": "report.pdf",
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document config not found.",
            examples=[
                OpenApiExample(
                    name="Not found",
                    value={"error": "Document config [1] not found"},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIGS_BULK_UPDATE_PUT = dict(
    summary="Bulk update multiple document configs",
    description=(
        "Bulk update multiple document configs with partial success support.\n"
        "Apply same parameters to selected configs by their config IDs.\n\n"
        "URL: GET /naive-rag/{naive_rag_id}/document-configs/bulk-update/\n\n"
        "Business Logic:\n"
        "- Validates each config individually\n"
        "- Updates configs that pass validation\n"
        "- Returns errors for configs that fail validation\n"
        "- Configs retain their current DB values when validation fails"
    ),
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="All configs updated successfully.",
            examples=[
                OpenApiExample(
                    name="All updated",
                    value={
                        "message": "Successfully updated 2 config(s)",
                        "updated_count": 2,
                        "failed_count": 0,
                        "configs": [
                            {
                                "naive_rag_document_id": 1,
                                "document_id": 10,
                                "file_name": "report.pdf",
                                "chunk_strategy": "character",
                                "chunk_size": 1500,
                                "chunk_overlap": 200,
                                "additional_params": {},
                                "status": "processed",
                                "total_chunks": 20,
                                "total_embeddings": 20,
                                "created_at": "2024-01-01T00:00:00Z",
                                "processed_at": "2024-01-01T00:01:00Z",
                                "errors": None,
                            },
                            {
                                "naive_rag_document_id": 2,
                                "document_id": 11,
                                "file_name": "notes.docx",
                                "chunk_strategy": "character",
                                "chunk_size": 1500,
                                "chunk_overlap": 200,
                                "additional_params": {},
                                "status": "pending",
                                "total_chunks": 0,
                                "total_embeddings": 0,
                                "created_at": "2024-01-02T00:00:00Z",
                                "processed_at": None,
                                "errors": None,
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        207: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Partial success — some configs updated, some failed.",
            examples=[
                OpenApiExample(
                    name="Partial success",
                    value={
                        "message": "Successfully updated 1 config(s), Failed to update 1 config(s)",
                        "updated_count": 1,
                        "failed_count": 1,
                        "configs": [
                            {
                                "naive_rag_document_id": 1,
                                "document_id": 10,
                                "file_name": "report.pdf",
                                "chunk_strategy": "character",
                                "chunk_size": 1500,
                                "chunk_overlap": 200,
                                "additional_params": {},
                                "status": "processed",
                                "total_chunks": 20,
                                "total_embeddings": 20,
                                "created_at": "2024-01-01T00:00:00Z",
                                "processed_at": "2024-01-01T00:01:00Z",
                                "errors": None,
                            },
                            {
                                "naive_rag_document_id": 2,
                                "document_id": 11,
                                "file_name": "notes.docx",
                                "chunk_strategy": "character",
                                "chunk_size": 1500,
                                "chunk_overlap": 200,
                                "additional_params": {},
                                "status": "pending",
                                "total_chunks": 0,
                                "total_embeddings": 0,
                                "created_at": "2024-01-02T00:00:00Z",
                                "processed_at": None,
                                "errors": {
                                    "chunk_size": [
                                        "chunk_size must be greater than chunk_overlap"
                                    ]
                                },
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["207"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid request parameters.",
            examples=[
                OpenApiExample(
                    name="Invalid parameters",
                    value={
                        "error": "At least one field must be provided for update: chunk_size, chunk_overlap, chunk_strategy, or additional_params"
                    },
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document config not found.",
            examples=[
                OpenApiExample(
                    name="Not found",
                    value={"error": "Document config [1] not found"},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIGS_BULK_DELETE_POST = dict(
    summary="Bulk delete multiple document configs",
    description="Bulk delete multiple document configs by their config IDs.\n\nURL: GET /naive-rag/{naive_rag_id}/document-configs/bulk-delete/",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Configs deleted successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "Successfully deleted 2 config(s)",
                        "deleted_count": 2,
                        "deleted_config_ids": [1, 2],
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid request parameters.",
            examples=[
                OpenApiExample(
                    name="Invalid parameters",
                    value={"error": "config_ids list cannot be empty"},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag not found.",
            examples=[
                OpenApiExample(
                    name="Not found",
                    value={"error": "NaiveRag not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIGS_INITIALIZE_POST = dict(
    summary="Initialize document configs for documents without configs",
    description=(
        "Manually initialize document configs for documents without configs.\n\n"
        "URL: GET /naive-rag/{naive_rag_id}/document-configs/initialize/\n\n"
        "Business Logic:\n"
        "- Creates configs for documents that DON'T have configs yet\n"
        "- Useful for:\n"
        "  1. Restoring accidentally deleted configs\n"
        "  2. Adding configs for new files added to collection after RAG creation\n"
        "- Existing configs are NOT modified\n"
        "- Idempotent: safe to call multiple times"
    ),
    responses={
        201: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Configs created successfully.",
            examples=[
                OpenApiExample(
                    name="Configs initialized",
                    value={
                        "message": "Initialized 2 new document config(s)",
                        "configs_created": 2,
                        "configs_existing": 1,
                        "new_configs": [
                            {
                                "config_id": 3,
                                "document_id": 12,
                                "file_name": "summary.pdf",
                                "file_type": "pdf",
                                "chunk_strategy": "fixed",
                            },
                            {
                                "config_id": 4,
                                "document_id": 13,
                                "file_name": "data.csv",
                                "file_type": "csv",
                                "chunk_strategy": "fixed",
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["201"],
                )
            ],
        ),
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="All documents already have configs.",
            examples=[
                OpenApiExample(
                    name="No new configs needed",
                    value={
                        "message": "All documents already have configs",
                        "configs_created": 0,
                        "configs_existing": 2,
                        "new_configs": [],
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag not found.",
            examples=[
                OpenApiExample(
                    name="NaiveRag not found",
                    value={"error": "NaiveRag not found."},
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
                    name="Server error",
                    value={"error": "Failed to initialize configs: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_GET = dict(
    summary="Get detailed NaiveRag info including all document configs",
    description="Get detailed NaiveRag info including all document configs.\n\nURL: GET /naive-rag/{naive_rag_id}/",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag retrieved successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "naive_rag_id": 1,
                        "base_rag_type": {
                            "base_rag_type_id": 3,
                            "source_collection_id": 7,
                        },
                        "embedder": 2,
                        "embedder_name": "text-embedding-3-small",
                        "rag_status": "completed",
                        "collection_id": 7,
                        "collection_name": "My Knowledge Base",
                        "total_documents": 3,
                        "configured_documents": 3,
                        "document_configs": [
                            {
                                "naive_rag_document_id": 1,
                                "document_id": 10,
                                "file_name": "report.pdf",
                                "chunk_strategy": "fixed",
                                "chunk_size": 512,
                                "chunk_overlap": 50,
                                "additional_params": {},
                                "status": "completed",
                                "total_chunks": 20,
                                "total_embeddings": 20,
                                "created_at": "2024-01-01T00:00:00Z",
                                "processed_at": "2024-01-01T00:01:00Z",
                            },
                            {
                                "naive_rag_document_id": 2,
                                "document_id": 11,
                                "file_name": "notes.docx",
                                "chunk_strategy": "fixed",
                                "chunk_size": 512,
                                "chunk_overlap": 50,
                                "additional_params": {},
                                "status": "pending",
                                "total_chunks": 0,
                                "total_embeddings": 0,
                                "created_at": "2024-01-02T00:00:00Z",
                                "processed_at": None,
                            },
                        ],
                        "error_message": None,
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:05:00Z",
                        "indexed_at": "2024-01-01T00:06:00Z",
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag not found.",
            examples=[
                OpenApiExample(
                    name="NaiveRag not found",
                    value={"error": "NaiveRag not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DELETE = dict(
    summary="Delete NaiveRag and all its configurations",
    description="Delete NaiveRag and all its configurations.\n\nURL: GET /naive-rag/{naive_rag_id}/",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag deleted successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "NaiveRag deleted successfully",
                        "naive_rag_id": 1,
                        "collection_id": 7,
                        "deleted_config_count": 3,
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag not found.",
            examples=[
                OpenApiExample(
                    name="NaiveRag not found",
                    value={"error": "NaiveRag not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_DOCUMENT_CONFIGS_PROCESS_CHUNKING_POST = dict(
    summary="Trigger document chunking and wait for completion",
    description=(
        "Trigger document chunking and wait for completion.\n\n"
        "URL: GET /naive-rag/{naive_rag_id}/document-configs/{document_config_id}/process-chinking/\n\n"
        "Flow:\n"
        "1. Validate document config exists and belongs to naive_rag\n"
        "2. Generate chunking_job_id (UUID)\n"
        "3. Update document config status to CHUNKING\n"
        "4. Publish message to Redis and wait for response (50s timeout)\n"
        "5. Return result (completed, failed, cancelled, or timeout)"
    ),
    responses={
        200: ChunkingResponseSerializer,
        202: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Chunking is still in progress (timeout) — may complete in background.",
            examples=[
                OpenApiExample(
                    name="Chunking timeout",
                    value={
                        "chunking_job_id": "550e8400-e29b-41d4-a716-446655440000",
                        "naive_rag_id": 1,
                        "document_config_id": 5,
                        "status": "timeout",
                        "chunk_count": None,
                        "message": "Chunking is taking longer than expected. Check status later or retry.",
                        "elapsed_time": None,
                    },
                    response_only=True,
                    status_codes=["202"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag or DocumentConfig not found.",
            examples=[
                OpenApiExample(
                    name="DocumentConfig not found",
                    value={"error": "DocumentConfig 5 not found for NaiveRag 1"},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Chunking failed due to an internal error.",
            examples=[
                OpenApiExample(
                    name="Chunking failed",
                    value={
                        "chunking_job_id": "550e8400-e29b-41d4-a716-446655440000",
                        "naive_rag_id": 1,
                        "document_config_id": 5,
                        "status": "failed",
                        "chunk_count": None,
                        "message": "<error detail>",
                        "elapsed_time": None,
                    },
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_COLLECTIONS_POST = dict(
    summary="Create new NaiveRag or update existing one for a collection",
    description=(
        "Create new NaiveRag or update existing one for a collection.\n"
        "Creates BaseRagType + NaiveRag in one step.\n\n"
        "URL: GET /naive-rag/collections/{collection_id}/naive-rag/"
    ),
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag configured successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "message": "NaiveRag configured successfully",
                        "naive_rag": {
                            "naive_rag_id": 1,
                            "base_rag_type": {
                                "base_rag_type_id": 3,
                                "source_collection_id": 7,
                            },
                            "embedder": 2,
                            "embedder_name": "text-embedding-3-small",
                            "rag_status": "new",
                            "collection_id": 7,
                            "error_message": None,
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-01-01T00:00:00Z",
                            "indexed_at": None,
                        },
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid request or RAG configuration error.",
            examples=[
                OpenApiExample(
                    name="Invalid embedder_id",
                    value={"embedder_id": ["This field is required."]},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection or embedder not found.",
            examples=[
                OpenApiExample(
                    name="Collection not found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

NAIVE_RAG_COLLECTIONS_GET = dict(
    summary="Get NaiveRag for a collection",
    description="Get NaiveRag for a collection.\n\nURL: GET /naive-rag/collections/{collection_id}/naive-rag/",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag retrieved successfully.",
            examples=[
                OpenApiExample(
                    name="Success",
                    value={
                        "naive_rag_id": 1,
                        "base_rag_type": {
                            "base_rag_type_id": 3,
                            "source_collection_id": 7,
                        },
                        "embedder": 2,
                        "embedder_name": "text-embedding-3-small",
                        "rag_status": "completed",
                        "collection_id": 7,
                        "error_message": None,
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:05:00Z",
                        "indexed_at": "2024-01-01T00:06:00Z",
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="NaiveRag not found for the given collection.",
            examples=[
                OpenApiExample(
                    name="Not found",
                    value={"error": "NaiveRag not found for collection 7"},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
        500: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Unexpected server error.",
            examples=[
                OpenApiExample(
                    name="Server error",
                    value={"error": "An unexpected error occurred: <detail>"},
                    response_only=True,
                    status_codes=["500"],
                )
            ],
        ),
    },
)

PROCESS_RAG_INDEXING_POST = dict(
    summary="Trigger (re)indexing of a RAG, optionally for a subset of documents",
    description=(
        "Start indexing for a NaiveRag or GraphRag.\n\n"
        "Body: `rag_id` (int), `rag_type` ('naive' | 'graph'), and for naive an "
        "optional `document_config_ids` (int[]). Without `document_config_ids` "
        "the whole RAG is considered; with it — only the listed docs (ignored "
        "for graph).\n\n"
        "Per-document decision (naive): if live chunk params match the "
        "`indexed_*` snapshot the doc is short-circuited to COMPLETED and "
        "returned in `skipped_completed_config_ids`. Docs currently being "
        "processed go into `skipped_in_progress_config_ids`. The rest go to "
        "`accepted_config_ids` and are queued.\n\n"
        "200 — nothing to dispatch (everything up-to-date or in progress).\n"
        "202 — work queued.\n\n"
        "URL: POST /process-rag-indexing/"
    ),
    request=ProcessRagIndexingSerializer,
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Nothing to index — all targeted documents are up-to-date or in progress.",
            examples=[
                OpenApiExample(
                    name="Nothing to index",
                    value={
                        "detail": "Nothing to index",
                        "rag_id": 1,
                        "rag_type": "naive",
                        "collection_id": 7,
                        "accepted_config_ids": [],
                        "skipped_completed_config_ids": [10, 11],
                        "skipped_in_progress_config_ids": [],
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        202: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Indexing process accepted and queued.",
            examples=[
                OpenApiExample(
                    name="Accepted",
                    value={
                        "detail": "Indexing process accepted",
                        "rag_id": 1,
                        "rag_type": "naive",
                        "collection_id": 7,
                        "accepted_config_ids": [12, 13],
                        "skipped_completed_config_ids": [10, 11],
                        "skipped_in_progress_config_ids": [],
                    },
                    response_only=True,
                    status_codes=["202"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid request or RAG not ready for indexing.",
            examples=[
                OpenApiExample(
                    name="Invalid serializer",
                    value={"rag_type": ['"invalid" is not a valid choice.']},
                    response_only=True,
                    status_codes=["400"],
                ),
                OpenApiExample(
                    name="RAG not ready",
                    value={
                        "status_code": 400,
                        "code": "rag_error",
                        "message": "RagNotReadyForIndexingException: <detail>",
                    },
                    response_only=True,
                    status_codes=["400"],
                ),
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="RAG configuration not found.",
            examples=[
                OpenApiExample(
                    name="NaiveRag not found",
                    value={
                        "status_code": 400,
                        "code": "rag_error",
                        "message": "NaiveRagNotFoundException: NaiveRag with id 1 not found",
                    },
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
    },
)
