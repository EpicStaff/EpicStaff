from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse
from tables.serializers.knowledge_serializers import (
    DocumentDetailSerializer,
    DocumentListSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

DOCUMENTS_LIST_GET = dict(
    summary="List all documents or filter by collection ID",
    description="List all documents or filter by collection ID",
    responses={
        200: DocumentListSerializer(many=True),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid collection_id parameter.",
            examples=[
                OpenApiExample(
                    name="Invalid collection_id",
                    value={"error": "Invalid collection_id parameter."},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
            examples=[
                OpenApiExample(
                    name="Collection not found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
    },
)

DOCUMENTS_RETRIEVE_GET = dict(
    summary="Retrieve a single document by ID",
    description="Retrieve a single document by ID",
    responses={
        200: DocumentDetailSerializer(),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document not found.",
            examples=[
                OpenApiExample(
                    name="Document not found",
                    value={"detail": "No DocumentMetadata matches the given query."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
    },
)

DOCUMENTS_DESTROY_DELETE = dict(
    summary="Delete a single document",
    description="Delete a single document",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document deleted successfully.",
            examples=[
                OpenApiExample(
                    name="Deleted",
                    value={
                        "message": "Document deleted successfully",
                        "document_id": 1,
                        "file_name": "report.pdf",
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document not found.",
            examples=[
                OpenApiExample(
                    name="Document not found",
                    value={"error": "Document not found."},
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

DOCUMENTS_UPLOAD_POST = dict(
    summary="Upload one or multiple files to a collection",
    description="Upload one or multiple files to a collection",
    responses={
        201: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Documents uploaded successfully.",
            examples=[
                OpenApiExample(
                    name="Uploaded",
                    value={
                        "message": "Successfully uploaded 2 file(s)",
                        "documents": [
                            {
                                "document_id": 1,
                                "file_name": "report.pdf",
                                "file_type": "pdf",
                                "file_size": 204800,
                                "source_collection": 3,
                            },
                            {
                                "document_id": 2,
                                "file_name": "notes.docx",
                                "file_type": "docx",
                                "file_size": 51200,
                                "source_collection": 3,
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["201"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error — invalid file type, size exceeded, or no files provided.",
            examples=[
                OpenApiExample(
                    name="Validation error",
                    value={"error": "Invalid file type."},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
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

DOCUMENTS_BULK_DELETE_POST = dict(
    summary="Delete multiple documents at once",
    description="Delete multiple documents at once",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Documents deleted successfully.",
            examples=[
                OpenApiExample(
                    name="Deleted",
                    value={
                        "message": "Successfully deleted 2 document(s)",
                        "deleted_documents": [
                            {"document_id": 1, "file_name": "report.pdf"},
                            {"document_id": 2, "file_name": "notes.docx"},
                        ],
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error.",
            examples=[
                OpenApiExample(
                    name="Validation error",
                    value={"document_ids": ["This field is required."]},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="One or more documents not found.",
            examples=[
                OpenApiExample(
                    name="Document not found",
                    value={"error": "Document not found."},
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

DOCUMENTS_DOWNLOAD_GET = dict(
    summary="Download one or multiple documents",
    description=(
        "Download documents by ID. A single document is returned as a file; "
        "multiple documents are bundled into a zip archive."
    ),
    parameters=[
        OpenApiParameter(
            name="document_ids",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Comma-separated list of document IDs (e.g. `1,2,3`).",
        )
    ],
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.BINARY,
            description="File or zip archive attachment.",
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Missing or invalid document_ids parameter.",
            examples=[
                OpenApiExample(
                    name="Missing parameter",
                    value={"error": "document_ids query parameter is required"},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="One or more documents not found.",
            examples=[
                OpenApiExample(
                    name="Documents not found",
                    value={"error": "Documents not found: 5, 6"},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
    },
)

DOCUMENTS_PREVIEW_GET = dict(
    summary="Preview a single document inline",
    description=(
        "Return the raw binary content of a single document for inline preview "
        "(`Content-Disposition: inline`). The browser can render supported formats "
        "(pdf, txt, md, json, html, csv) in place; docx has no native preview and "
        "is downloaded instead. Use the download endpoint to force a file download."
    ),
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.BINARY,
            description="Raw file content served inline.",
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Document not found.",
            examples=[
                OpenApiExample(
                    name="Document not found",
                    value={"detail": "No DocumentMetadata matches the given query."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
    },
)

DOCUMENTS_COPY_POST = dict(
    summary="Copy documents into a target collection",
    description=(
        "Copy documents into a target collection by ID. Binary content is shared "
        "(not duplicated): new document records point to the same stored content. "
        "Documents whose content is already present in the target collection are "
        "skipped and returned under `skipped`."
    ),
    responses={
        201: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Documents copied successfully.",
            examples=[
                OpenApiExample(
                    name="Copied",
                    value={
                        "message": (
                            "Successfully copied 1 document(s), skipped 1 already "
                            "present in the target collection"
                        ),
                        "documents": [
                            {
                                "document_id": 10,
                                "file_name": "report.pdf",
                                "file_type": "pdf",
                                "file_size": 204800,
                                "source_collection": 15,
                            },
                        ],
                        "skipped": [
                            {
                                "document_id": 4,
                                "file_name": "notes.docx",
                                "file_type": "docx",
                                "file_size": 51200,
                                "source_collection": 8,
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["201"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Validation error.",
            examples=[
                OpenApiExample(
                    name="Validation error",
                    value={"document_ids": ["This field is required."]},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Target collection or one or more documents not found.",
            examples=[
                OpenApiExample(
                    name="Collection not found",
                    value={"error": "Source collection with id 15 not found"},
                    response_only=True,
                    status_codes=["404"],
                ),
                OpenApiExample(
                    name="Documents not found",
                    value={"error": "Documents not found: 5, 6"},
                    response_only=True,
                    status_codes=["404"],
                ),
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

COLLECTION_DOCUMENTS_LIST_GET = dict(
    summary="List all documents or filter by collection ID",
    description="List all documents or filter by collection ID.\n\nURL: GET /source-collection/{id}/documents",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Documents listed successfully.",
            examples=[
                OpenApiExample(
                    name="Documents listed",
                    value={
                        "collection_id": 3,
                        "collection_name": "Research Papers",
                        "document_count": 2,
                        "documents": [
                            {
                                "document_id": 1,
                                "file_name": "report.pdf",
                                "file_type": "pdf",
                                "file_size": 204800,
                            },
                            {
                                "document_id": 2,
                                "file_name": "notes.docx",
                                "file_type": "docx",
                                "file_size": 51200,
                            },
                        ],
                    },
                    response_only=True,
                    status_codes=["200"],
                )
            ],
        ),
        400: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Invalid collection_id parameter.",
            examples=[
                OpenApiExample(
                    name="Invalid collection_id",
                    value={"error": "Invalid collection_id parameter."},
                    response_only=True,
                    status_codes=["400"],
                )
            ],
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        404: OpenApiResponse(
            response=OpenApiTypes.STR,
            description="Collection not found.",
            examples=[
                OpenApiExample(
                    name="Collection not found",
                    value={"error": "Collection not found."},
                    response_only=True,
                    status_codes=["404"],
                )
            ],
        ),
    },
)
