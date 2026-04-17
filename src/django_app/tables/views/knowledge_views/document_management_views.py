from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from rest_framework import serializers as drf_serializers

from tables.models import DocumentMetadata
from tables.serializers.knowledge_serializers import (
    DocumentMetadataSerializer,
    DocumentUploadSerializer,
    DocumentBulkDeleteSerializer,
    DocumentListSerializer,
    DocumentDetailSerializer,
)
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)
from tables.exceptions import (
    DocumentUploadException,
    FileSizeExceededException,
    InvalidFileTypeException,
    CollectionNotFoundException,
    NoFilesProvidedException,
    DocumentNotFoundException,
    InvalidFieldType,
)


class DocumentManagementViewSet(viewsets.GenericViewSet):
    """
    ViewSet for document upload operations within a collection.

    Endpoints:
    - POST /source-collections/{collection_id}/documents/upload/ - Upload files
    - POST /documents/bulk-delete/ - Delete multiple documents
    """

    def get_serializer_class(self):
        if self.action == "upload_documents":
            return DocumentUploadSerializer
        elif self.action == "bulk_delete":
            return DocumentBulkDeleteSerializer
        return DocumentMetadataSerializer

    @action(
        detail=False,
        methods=["post"],
        url_path="source-collections/(?P<collection_id>[^/.]+)/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_documents(self, request, collection_id=None):
        """
        Upload one or multiple files to a collection.
        Request (multipart/form-data):
            - files: List of files to upload

        URL: POST /documents/source-collections/{collection_id}/upload/

        Returns:
        - 201: Successfully uploaded documents
        - 400: Validation errors
        - 404: Collection not found
        """

        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        files = serializer.validated_data["files"]

        try:
            # Use service to handle all business logic
            created_documents = DocumentManagementService.upload_files_batch(
                collection_id=collection_id, uploaded_files=files
            )

            # Serialize response
            response_serializer = DocumentMetadataSerializer(
                created_documents, many=True
            )

            return Response(
                {
                    "message": f"Successfully uploaded {len(created_documents)} file(s)",
                    "documents": response_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )

        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except NoFilesProvidedException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (FileSizeExceededException, InvalidFileTypeException) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DocumentUploadException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-delete",
    )
    def bulk_delete(self, request):
        """
        Delete multiple documents at once.

        URL: POST /documents/bulk-delete/

        Request body (JSON):
        {
            "document_ids": [1, 2, 3, 4, 5]
        }

        Returns:
        - 200: Successfully deleted documents
        - 400: Validation errors
        - 404: One or more documents not found
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document_ids = serializer.validated_data["document_ids"]

        try:
            # Use service to handle deletion
            result = DocumentManagementService.delete_documents_batch(document_ids)

            return Response(
                {
                    "message": f"Successfully deleted {result['deleted_count']} document(s)",
                    "deleted_documents": result["documents"],
                },
                status=status.HTTP_200_OK,
            )

        except DocumentNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except DocumentUploadException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DocumentViewSet(
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for document CRUD operations.

    Endpoints:
    - GET /documents/ - List all documents
    - GET /documents/{id}/ - Retrieve single document
    - DELETE /documents/{id}/ - Delete single document
    - GET /source-collections/{collection_id}/documents/ - List collection documents
    """

    queryset = DocumentMetadata.objects.select_related("source_collection")

    def get_serializer_class(self):
        if self.action == "list":
            return DocumentListSerializer
        elif self.action == "retrieve":
            return DocumentDetailSerializer
        return DocumentMetadataSerializer

    @extend_schema(
        description="List all documents or filter by collection ID",
        parameters=[
            OpenApiParameter(
                name="collection_id",
                location=OpenApiParameter.QUERY,
                description="Filter documents by collection ID",
                type=drf_serializers.IntegerField(),
                required=False,
            )
        ],
        responses={
            200: DocumentListSerializer(many=True),
            400: OpenApiResponse(description="Invalid collection_id parameter"),
            404: OpenApiResponse(description="Collection not found"),
        },
    )
    def list(self, request, *args, **kwargs):
        """
        List all documents or filter by collection.

        Query parameters:
        - collection_id: Filter by collection ID
        """
        collection_id = request.query_params.get("collection_id")
        queryset = DocumentManagementService.get_documents_list(
            collection_id=collection_id
        )

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a single document by ID.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """
        Delete a single document.
        """
        instance = self.get_object()
        document_id = instance.document_id
        file_name = instance.file_name

        try:
            # Use service for deletion
            result = DocumentManagementService.delete_document(document_id)

            return Response(
                {
                    "message": "Document deleted successfully",
                    "document_id": result["document_id"],
                    "file_name": result["file_name"],
                },
                status=status.HTTP_200_OK,
            )

        except DocumentNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CollectionDocumentsViewSet(viewsets.GenericViewSet):
    """
    ViewSet for accessing documents within a specific collection.

    Nested route: /source-collections/{collection_id}/documents/
    """

    def get_queryset(self):
        collection_id = self.kwargs.get("collection_id")
        return DocumentMetadata.objects.filter(
            source_collection_id=collection_id
        ).select_related("source_collection")

    def get_serializer_class(self):
        return DocumentListSerializer

    def list(self, request, collection_id=None):
        """
        List all documents in a specific collection.

        URL: GET /source-collections/{collection_id}/documents/
        """
        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        # Verify collection exists
        try:
            collection = DocumentManagementService.get_collection(collection_id)
        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response(
            {
                "collection_id": collection.collection_id,
                "collection_name": collection.collection_name,
                "document_count": queryset.count(),
                "documents": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
