from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from rest_framework import serializers as drf_serializers

from rest_framework.permissions import IsAuthenticated

from tables.models import DocumentMetadata, SourceCollection
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
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
from tables.views.mixins import (
    OrgScopedChildViewSetMixin,
    OrgScopedServiceViewSetMixin,
)
from tables.services.rbac.permissions import HasOrgPermission
from tables.services.rbac.permission_action_map import DEFAULT_ACTION_MAP

from tables.swagger_schemas.knowledge_schemas.document_management_schemas import (
    DOCUMENTS_LIST_GET,
    DOCUMENTS_RETRIEVE_GET,
    DOCUMENTS_DESTROY_DELETE,
    DOCUMENTS_UPLOAD_POST,
    DOCUMENTS_BULK_DELETE_POST,
    COLLECTION_DOCUMENTS_LIST_GET,
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


_DOCUMENT_ORG_PATH = "source_collection__org_id"


class DocumentManagementViewSet(OrgScopedServiceViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for document upload operations within a collection.

    Endpoints:
    - POST /source-collections/{collection_id}/documents/upload/ - Upload files
    - POST /documents/bulk-delete/ - Delete multiple documents
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.KNOWLEDGE_SOURCES
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "upload_documents": Permission.CREATE,
        "bulk_delete": Permission.DELETE,
    }

    def get_serializer_class(self):
        if self.action == "upload_documents":
            return DocumentUploadSerializer
        elif self.action == "bulk_delete":
            return DocumentBulkDeleteSerializer
        return DocumentMetadataSerializer

    @extend_schema(**DOCUMENTS_UPLOAD_POST)
    @action(
        detail=False,
        methods=["post"],
        url_path="source-collections/(?P<collection_id>[^/.]+)/upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_documents(self, request, collection_id=None):
        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        # The collection must live in the active org (404 otherwise).
        self.get_in_active_org_or_404(SourceCollection, collection_id)

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

    @extend_schema(**DOCUMENTS_BULK_DELETE_POST)
    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-delete",
    )
    def bulk_delete(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document_ids = serializer.validated_data["document_ids"]
        # Narrow to documents the active org owns — other-org ids are ignored.
        document_ids = list(
            DocumentMetadata.objects.filter(
                document_id__in=document_ids,
                **{_DOCUMENT_ORG_PATH: self.get_active_org_id()},
            ).values_list("document_id", flat=True)
        )

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
    OrgScopedChildViewSetMixin,
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

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.KNOWLEDGE_SOURCES
    org_filter_path = _DOCUMENT_ORG_PATH
    queryset = DocumentMetadata.objects.select_related("source_collection")

    def get_serializer_class(self):
        if self.action == "list":
            return DocumentListSerializer
        elif self.action == "retrieve":
            return DocumentDetailSerializer
        return DocumentMetadataSerializer

    @extend_schema(**DOCUMENTS_LIST_GET)
    def list(self, request, *args, **kwargs):
        # get_queryset() is org-scoped via OrgScopedChildViewSetMixin.
        queryset = self.get_queryset()
        collection_id = request.query_params.get("collection_id")
        if collection_id:
            queryset = queryset.filter(source_collection_id=collection_id)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(**DOCUMENTS_RETRIEVE_GET)
    def retrieve(self, request, *args, **kwargs):
        """
        Retrieve a single document by ID.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @extend_schema(**DOCUMENTS_DESTROY_DELETE)
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


class CollectionDocumentsViewSet(OrgScopedServiceViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for accessing documents within a specific collection.

    Nested route: /source-collections/{collection_id}/documents/
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.KNOWLEDGE_SOURCES

    def get_queryset(self):
        collection_id = self.kwargs.get("collection_id")
        return DocumentMetadata.objects.filter(
            source_collection_id=collection_id,
            **{_DOCUMENT_ORG_PATH: self.get_active_org_id()},
        ).select_related("source_collection")

    def get_serializer_class(self):
        return DocumentListSerializer

    @extend_schema(**COLLECTION_DOCUMENTS_LIST_GET)
    def list(self, request, collection_id=None):
        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        # Collection must be in the active org (404 otherwise).
        collection = self.get_in_active_org_or_404(SourceCollection, collection_id)

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
