from rest_framework import viewsets, status
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiParameter,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from utils.logger import logger
from rest_framework.response import Response
from rest_framework.decorators import action

from tables.models.knowledge_models.collection_models import SourceCollection

from tables.serializers.knowledge_serializers import (
    SourceCollectionListSerializer,
    SourceCollectionDetailSerializer,
    SourceCollectionCreateSerializer,
    SourceCollectionUpdateSerializer,
    CopySourceCollectionSerializer,
)

from tables.services.redis_service import RedisService
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.swagger_schemas.knowledge_schemas.collection_management_schemas import (
    SOURCE_COLLECTIONS_GET,
    SOURCE_COLLECTION_GET,
    SOURCE_COLLECTION_POST,
    SOURCE_COLLECTION_PATCH,
    SOURCE_COLLECTION_PUT,
    SOURCE_COLLECTION_DELETE,
    SOURCE_COLLECTION_BULK_DELETE_POST,
    SOURCE_COLLECTION_COPY_POST,
    SOURCE_COLLECTION_AVAILABLE_RAGS_GET,
)
from tables.exceptions import CollectionNotFoundException

redis_service = RedisService()


class SourceCollectionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for SourceCollection CRUD operations.

    Endpoints:
    - GET /source-collections/ - List all collections
    - GET /source-collections/{id}/ - Retrieve a specific collection
    - POST /source-collections/ - Create a new empty collection
    - POST /source-collections/{id}/copy/ - Copy collection (shares content)
    - PATCH /source-collections/{id}/ - Update collection name
    - PUT /source-collections/{id}/ - Update collection name
    - DELETE /source-collections/{id}/ - Delete collection (cleans unreferenced content)
    - POST /source-collections/bulk-delete/ - Bulk delete source collections
    - GET /source-collections/{id}/available-rags/ - Get available RAG configurations for a collection

    """

    http_method_names = ["get", "post", "patch", "put", "delete"]

    def get_queryset(self):
        """Optimize queries based on action."""
        queryset = SourceCollection.objects.all()

        if self.action in ("list", "retrieve"):
            queryset = queryset.prefetch_related(
                "documents",
                *CollectionManagementService.rag_configurations_prefetch(),
            )

        return queryset

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "list":
            return SourceCollectionListSerializer
        elif self.action == "retrieve":
            return SourceCollectionDetailSerializer
        elif self.action == "create":
            return SourceCollectionCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return SourceCollectionUpdateSerializer
        elif self.action == "copy":
            return CopySourceCollectionSerializer

        return SourceCollectionListSerializer

    @extend_schema(**SOURCE_COLLECTIONS_GET)
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(**SOURCE_COLLECTION_GET)
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @extend_schema(**SOURCE_COLLECTION_POST)
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            collection = CollectionManagementService.create_collection(
                collection_name=serializer.validated_data.get("collection_name"),
                user_id=serializer.validated_data.get("user_id"),
                collection_origin=serializer.validated_data.get("collection_origin"),
            )

            output_serializer = SourceCollectionDetailSerializer(collection)
            return Response(output_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": f"Failed to create collection: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(**SOURCE_COLLECTION_PUT)
    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @extend_schema(**SOURCE_COLLECTION_PATCH)
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            updated_collection = CollectionManagementService.update_collection(
                collection_id=instance.collection_id,
                collection_name=serializer.validated_data["collection_name"],
            )

            output_serializer = SourceCollectionDetailSerializer(updated_collection)
            return Response(output_serializer.data)

        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to update collection: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(**SOURCE_COLLECTION_DELETE)
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            result = CollectionManagementService.delete_collection(
                collection_id=instance.collection_id
            )

            return Response(
                {"message": "Collection deleted successfully", **result},
                status=status.HTTP_200_OK,
            )

        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to delete collection: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(**SOURCE_COLLECTION_BULK_DELETE_POST)
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        collection_ids = request.data.get("collection_ids", [])

        if not collection_ids:
            return Response(
                {"error": "collection_ids is required and must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(collection_ids, list):
            return Response(
                {"error": "collection_ids must be a list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = CollectionManagementService.bulk_delete_collections(collection_ids)

            return Response(
                {
                    "message": f"Successfully deleted {result['deleted_count']} collection(s)",
                    **result,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"Failed to delete collections: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(**SOURCE_COLLECTION_COPY_POST)
    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            new_collection = CollectionManagementService.copy_collection(
                source_collection_id=int(pk),
                new_collection_name=serializer.validated_data.get(
                    "new_collection_name"
                ),
            )

            output_serializer = SourceCollectionDetailSerializer(new_collection)

            return Response(
                {
                    "message": "Collection copied successfully",
                    "collection": output_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )

        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to copy collection: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(**SOURCE_COLLECTION_AVAILABLE_RAGS_GET)
    @action(detail=True, methods=["get"], url_path="available-rags")
    def available_rags(self, request, pk=None):
        try:
            # Get all RAG configurations for this collection
            rag_configs = CollectionManagementService.get_rag_configurations(int(pk))

            # Get status filter from query params (default to completed,warning)
            status_filter = request.query_params.get("status", "completed,warning,new")
            allowed_statuses = [
                s.strip() for s in status_filter.split(",") if s.strip()
            ]

            # Filter by status
            filtered_configs = [
                config
                for config in rag_configs
                if config.get("status") in allowed_statuses
            ]

            response_data = []
            for config in filtered_configs:
                response_data.append(
                    {
                        "rag_id": config.get("rag_id"),
                        "rag_type": config.get("rag_type"),
                        "rag_status": config.get("status"),
                        "collection_id": int(pk),
                        "created_at": config.get("created_at"),
                        "updated_at": config.get("updated_at"),
                    }
                )

            return Response(response_data, status=status.HTTP_200_OK)

        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error fetching available RAGs for collection {pk}: {str(e)}")
            return Response(
                {"error": f"Failed to fetch available RAGs: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
