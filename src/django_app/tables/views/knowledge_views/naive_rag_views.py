import asyncio
import uuid

from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.http import Http404
from rest_framework.exceptions import ValidationError
from asgiref.sync import async_to_sync
from loguru import logger

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.views import APIView

from tables.models.knowledge_models import (
    NaiveRag,
    NaiveRagDocumentConfig,
    NaiveRagChunk,
    NaiveRagPreviewChunk,
)
from tables.serializers.naive_rag_serializers import (
    NaiveRagSerializer,
    NaiveRagCreateUpdateSerializer,
    NaiveRagDetailSerializer,
    DocumentConfigSerializer,
    DocumentConfigWithErrorsSerializer,
    DocumentConfigUpdateSerializer,
    DocumentConfigBulkUpdateSerializer,
    DocumentConfigBulkDeleteSerializer,
    NaiveRagChunkSerializer,
    NaiveRagPreviewChunkSerializer,
    ChunkingResponseSerializer,
    ChunkPreviewResponseSerializer,
)
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tables.services.redis_service import RedisService

from tables.exceptions import (
    RagException,
    NaiveRagNotFoundException,
    DocumentConfigNotFoundException,
    EmbedderNotFoundException,
    InvalidChunkParametersException,
    CollectionNotFoundException,
    InvalidFieldType,
)
from tables.constants.knowledge_constants import CHUNKING_TIMEOUT


redis_service = RedisService()


class NaiveRagViewSet(viewsets.GenericViewSet):
    """
    ViewSet for NaiveRag operations.

    Endpoints:
    - POST /collections/{collection_id}/naive-rag/ - Create or update NaiveRag
    - GET /collections/{collection_id}/naive-rag/ - Get NaiveRag for collection
    - DELETE /naive-rag/{id}/ - Delete NaiveRag
    - GET /naive-rag/{id}/ - Get NaiveRag details with configs
    """

    queryset = NaiveRag.objects.all()
    serializer_class = NaiveRagSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return NaiveRag.objects.none()
        return super().get_queryset()

    def get_serializer_class(self):
        if self.action in ["create_or_update", "update_naive_rag"]:
            return NaiveRagCreateUpdateSerializer
        elif self.action == "retrieve":
            return NaiveRagDetailSerializer
        return NaiveRagSerializer

    @action(
        detail=False,
        methods=["post"],
        url_path="collections/(?P<collection_id>[^/.]+)/naive-rag",
    )
    def create_or_update(self, request, collection_id=None):
        """
        Create new NaiveRag or update existing one for a collection.
        Creates BaseRagType + NaiveRag in one step.

        URL: POST /naive-rag/collections/{collection_id}/naive-rag/

        Body:
        {
            "embedder_id": 1
        }
        """

        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        embedder_id = serializer.validated_data["embedder_id"]

        try:
            naive_rag = NaiveRagService.create_or_update_naive_rag(
                collection_id=collection_id, embedder_id=embedder_id
            )

            response_serializer = NaiveRagSerializer(naive_rag)

            return Response(
                {
                    "message": "NaiveRag configured successfully",
                    "naive_rag": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except EmbedderNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["get"],
        url_path="collections/(?P<collection_id>[^/.]+)/naive-rag",
    )
    def get_by_collection(self, request, collection_id=None):
        """
        Get NaiveRag for a collection.

        URL: GET /naive-rag/collections/{collection_id}/naive-rag/
        """

        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        try:
            naive_rag = NaiveRagService.get_or_none_naive_rag_by_collection(
                collection_id
            )

            if not naive_rag:
                return Response(
                    {"error": f"NaiveRag not found for collection {collection_id}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = NaiveRagSerializer(naive_rag)
            return Response(serializer.data)

        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None):
        """
        Get detailed NaiveRag info including all document configs.

        URL: GET /naive-rag/{id}/
        """
        try:
            naive_rag = NaiveRagService.get_naive_rag(int(pk))

            serializer = NaiveRagDetailSerializer(naive_rag)
            return Response(serializer.data)

        except NaiveRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def destroy(self, request, pk=None):
        """
        Delete NaiveRag and all its configurations.

        URL: DELETE /naive-rag/{id}/
        """
        try:
            result = NaiveRagService.delete_naive_rag(int(pk))

            return Response(
                {"message": "NaiveRag deleted successfully", **result},
                status=status.HTTP_200_OK,
            )

        except NaiveRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={},
            description="No body required - send empty JSON object {}",
        ),
        responses={
            201: "Configs created successfully",
            200: "All documents already have configs",
            404: "NaiveRag not found",
            500: "Internal server error",
        },
    )
    def initialize_configs(self, request, naive_rag_id=None):
        """
        Manually initialize document configs for documents without configs.

        Business Logic:
        - Creates configs for documents that DON'T have configs yet
        - Useful for:
          1. Restoring accidentally deleted configs
          2. Adding configs for new files added to collection after RAG creation
        - Existing configs are NOT modified
        - Idempotent: safe to call multiple times
        """
        try:
            naive_rag = NaiveRagService.get_naive_rag(int(naive_rag_id))

            # Initialize configs for documents without configs
            new_configs = NaiveRagService.init_document_configs(
                naive_rag_id=int(naive_rag_id)
            )

            existing_count = NaiveRagDocumentConfig.objects.filter(
                naive_rag=naive_rag
            ).count() - len(new_configs)

            new_configs_data = [
                {
                    "config_id": config.naive_rag_document_id,
                    "document_id": config.document.document_id,
                    "file_name": config.document.file_name,
                    "file_type": config.document.file_type,
                    "chunk_strategy": config.chunk_strategy,
                }
                for config in new_configs
            ]

            message = (
                f"Initialized {len(new_configs)} new document config(s)"
                if new_configs
                else "All documents already have configs"
            )

            return Response(
                {
                    "message": message,
                    "configs_created": len(new_configs),
                    "configs_existing": existing_count,
                    "new_configs": new_configs_data,
                },
                status=status.HTTP_201_CREATED if new_configs else status.HTTP_200_OK,
            )

        except NaiveRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"Failed to initialize configs: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class NaiveRagDocumentConfigViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for NaiveRag document configuration operations.

    All operations are scoped to a specific NaiveRag instance.
    Configs are validated to belong to the specified naive_rag_id.

    Endpoints:
    - GET /api/naive-rag/{naive_rag_id}/document-configs/ - List all configs
    - GET /api/naive-rag/{naive_rag_id}/document-configs/{pk}/ - Get single config
    - PUT /api/naive-rag/{naive_rag_id}/document-configs/{pk}/ - Update single config
    - DELETE /api/naive-rag/{naive_rag_id}/document-configs/{pk}/ - Delete single config
    - PUT /api/naive-rag/{naive_rag_id}/document-configs/bulk-update/ - Bulk update configs
    - POST /api/naive-rag/{naive_rag_id}/document-configs/bulk-delete/ - Bulk delete configs
    """

    queryset = NaiveRagDocumentConfig.objects.select_related("document")

    def get_serializer_class(self):
        if self.action == "bulk_update":
            return DocumentConfigBulkUpdateSerializer
        elif self.action == "bulk_delete":
            return DocumentConfigBulkDeleteSerializer
        elif self.action == "update":
            return DocumentConfigUpdateSerializer
        return DocumentConfigSerializer

    def get_queryset(self):
        """
        Filter queryset by naive_rag_id from URL.
        This ensures all operations are scoped to the specific NaiveRag.
        """
        queryset = super().get_queryset()
        naive_rag_id = self.kwargs.get("naive_rag_id")

        if naive_rag_id is not None:
            # Filter configs that belong to this naive_rag
            queryset = queryset.filter(naive_rag_id=naive_rag_id)

        return queryset

    def initial(self, request, *args, **kwargs):
        """
        Validate naive_rag_id before processing request.
        """
        super().initial(request, *args, **kwargs)

        naive_rag_id = self.kwargs.get("naive_rag_id")

        if naive_rag_id is not None:
            try:
                self.kwargs["naive_rag_id"] = int(naive_rag_id)
            except (ValueError, TypeError):
                raise ValidationError(
                    {
                        "naive_rag_id": f"Invalid value '{naive_rag_id}'. Must be an integer."
                    }
                )

    @action(detail=False, methods=["put"], url_path="bulk-update")
    def bulk_update(self, request, naive_rag_id=None):
        """
        Bulk update multiple document configs with partial success support.
        Apply same parameters to selected configs by their config IDs.

        Business Logic:
        - Validates each config individually
        - Updates configs that pass validation
        - Returns errors for configs that fail validation
        - Configs retain their current DB values when validation fails

        URL: PUT /api/naive-rag/{naive_rag_id}/document-configs/bulk-update/

        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        config_ids = serializer.validated_data.pop("config_ids")

        try:
            result = NaiveRagService.bulk_update_document_configs_with_partial_errors(
                naive_rag_id=int(naive_rag_id),
                config_ids=config_ids,
                **serializer.validated_data,
            )

            # Use the new serializer that includes errors field
            response_serializer = DocumentConfigWithErrorsSerializer(
                result["configs"],
                many=True,
                context={"config_errors": result["config_errors"]},
            )

            # Build status message
            if result["failed_count"] == 0:
                message = f"Successfully updated {result['updated_count']} config(s)"
                response_status = status.HTTP_200_OK
            elif result["updated_count"] == 0:
                message = f"Failed to update {result['failed_count']} config(s)"
                response_status = status.HTTP_207_MULTI_STATUS
            else:
                message = (
                    f"Successfully updated {result['updated_count']} config(s), "
                    f"Failed to update {result['failed_count']} config(s)"
                )
                response_status = status.HTTP_207_MULTI_STATUS

            return Response(
                {
                    "message": message,
                    "updated_count": result["updated_count"],
                    "failed_count": result["failed_count"],
                    "configs": response_serializer.data,
                },
                status=response_status,
            )

        except DocumentConfigNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except InvalidChunkParametersException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request, naive_rag_id=None):
        """
        Bulk delete multiple document configs by their config IDs.

        URL: POST /api/naive-rag/{naive_rag_id}/document-configs/bulk-delete/

        Body:
        {
            "config_ids": [1, 2, 3]  // Required: naive_rag_document_config IDs
        }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        config_ids = serializer.validated_data["config_ids"]

        try:
            result = NaiveRagService.bulk_delete_document_configs(
                naive_rag_id=int(naive_rag_id), config_ids=config_ids
            )

            return Response(
                {
                    "message": f"Successfully deleted {result['deleted_count']} config(s)",
                    **result,
                },
                status=status.HTTP_200_OK,
            )

        except DocumentConfigNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except InvalidChunkParametersException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def list_configs(self, request, naive_rag_id=None):
        """
        List all document configs for a NaiveRag.

        URL: GET /api/naive-rag/{naive_rag_id}/document-configs/
        """
        try:
            configs = NaiveRagService.get_document_configs_for_naive_rag(
                int(naive_rag_id)
            )

            serializer = DocumentConfigSerializer(configs, many=True)

            return Response(
                {
                    "naive_rag_id": int(naive_rag_id),
                    "total_configs": len(configs),
                    "configs": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except NaiveRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None, naive_rag_id=None):
        """
        Get single document config.

        URL: GET /api/naive-rag/{naive_rag_id}/document-configs/{pk}/
        """
        try:
            config = self.get_object()
            serializer = DocumentConfigSerializer(config)
            return Response(serializer.data)

        except Http404:
            return Response(
                {
                    "error": f"Document config [{pk}] for naive_rag_id [{naive_rag_id}] not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def update(self, request, pk=None, naive_rag_id=None):
        """
        Update single document config.

        URL: PUT /api/naive-rag/{naive_rag_id}/document-configs/{pk}/

        Body (all fields optional):
        {
            "chunk_size": 1500,
            "chunk_overlap": 200,
            "chunk_strategy": "character",
            "additional_params": {}
        }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            config = NaiveRagService.update_document_config(
                config_id=int(pk),
                naive_rag_id=naive_rag_id,
                **serializer.validated_data,
            )

            response_serializer = DocumentConfigSerializer(config)

            return Response(
                {
                    "message": "Document config updated successfully",
                    "config": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except DocumentConfigNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except InvalidChunkParametersException as e:
            return Response({"errors": e.errors}, status=status.HTTP_400_BAD_REQUEST)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def destroy(self, request, pk=None, naive_rag_id=None):
        """
        Delete a single document config.

        URL: DELETE /api/naive-rag/{naive_rag_id}/document-configs/{pk}/
        """
        try:
            result = NaiveRagService.delete_document_config(
                config_id=int(pk), naive_rag_id=int(naive_rag_id)
            )

            return Response(
                {
                    "message": "Document config deleted successfully",
                    **result,
                },
                status=status.HTTP_200_OK,
            )

        except DocumentConfigNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class NaiveRagChunkViewSet(ReadOnlyModelViewSet):
    queryset = NaiveRagChunk.objects.all()
    serializer_class = NaiveRagChunkSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["naive_rag_document_config"]


class ProcessNaiveRagDocumentChunkingView(APIView):
    """
    Trigger document chunking and wait for completion.

    URL: POST /naive-rag/{naive_rag_id}/document-configs/{document_config_id}/process-chunking/

    Flow:
    1. Validate document config exists and belongs to naive_rag
    2. Generate chunking_job_id (UUID)
    3. Update document config status to CHUNKING
    4. Publish message to Redis and wait for response (50s timeout)
    5. Return result (completed, failed, cancelled, or timeout)
    """

    @swagger_auto_schema(
        operation_description="Trigger document chunking and wait for completion",
        responses={
            200: ChunkingResponseSerializer,
            202: "Chunking is still in progress (timeout)",
            404: "NaiveRag or DocumentConfig not found",
            500: "Internal server error",
        },
    )
    def post(self, request, naive_rag_id: int, document_config_id: int):
        # Validate document config exists and belongs to naive_rag
        try:
            config = NaiveRagDocumentConfig.objects.select_related(
                "naive_rag", "document"
            ).get(
                naive_rag_document_id=document_config_id,
                naive_rag_id=naive_rag_id,
            )
        except NaiveRagDocumentConfig.DoesNotExist:
            return Response(
                {
                    "error": f"DocumentConfig {document_config_id} not found "
                    f"for NaiveRag {naive_rag_id}"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        chunking_job_id = str(uuid.uuid4())

        config.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKING
        config.save(update_fields=["status"])

        logger.info(
            f"Starting chunking job {chunking_job_id} for config {document_config_id}"
        )

        try:
            # Publish and wait for response
            response = async_to_sync(redis_service.publish_and_wait_for_chunking)(
                rag_type="naive",
                document_config_id=document_config_id,
                chunking_job_id=chunking_job_id,
                timeout=CHUNKING_TIMEOUT,
            )

            config.refresh_from_db()

            return Response(
                {
                    "chunking_job_id": chunking_job_id,
                    "naive_rag_id": naive_rag_id,
                    "document_config_id": document_config_id,
                    "status": response.status,
                    "chunk_count": response.chunk_count,
                    "message": response.message,
                    "elapsed_time": response.elapsed_time,
                },
                status=status.HTTP_200_OK,
            )

        except asyncio.TimeoutError:
            logger.warning(
                f"Chunking timeout for job {chunking_job_id}, config {document_config_id}"
            )
            # Return partial success - chunking may still complete in background
            return Response(
                {
                    "chunking_job_id": chunking_job_id,
                    "naive_rag_id": naive_rag_id,
                    "document_config_id": document_config_id,
                    "status": "timeout",
                    "chunk_count": None,
                    "message": "Chunking is taking longer than expected. "
                    "Check status later or retry.",
                    "elapsed_time": None,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except Exception as e:
            logger.error(f"Chunking error for job {chunking_job_id}: {e}")
            # Reset status to previous state on error
            config.status = NaiveRagDocumentConfig.NaiveRagDocumentStatus.FAILED
            config.save(update_fields=["status"])

            return Response(
                {
                    "chunking_job_id": chunking_job_id,
                    "naive_rag_id": naive_rag_id,
                    "document_config_id": document_config_id,
                    "status": "failed",
                    "chunk_count": None,
                    "message": str(e),
                    "elapsed_time": None,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class NaiveRagChunkPreviewView(APIView):
    """
    Get chunks for a document config.

    URL: GET /naive-rag/{naive_rag_id}/document-configs/{document_config_id}/chunks/

    Returns:
    - Preview chunks if status is CHUNKED (not yet indexed)
    - Indexed chunks if status is COMPLETED

    Supports pagination for endless scrolling:
    - limit: Number of chunks to return (default: 50)
    - offset: Number of chunks to skip (default: 0)
    """

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 500

    @swagger_auto_schema(
        operation_description="Get chunks for a document config (preview or indexed)",
        manual_parameters=[
            openapi.Parameter(
                "limit",
                openapi.IN_QUERY,
                description="Number of chunks to return (max 500)",
                type=openapi.TYPE_INTEGER,
                default=50,
            ),
            openapi.Parameter(
                "offset",
                openapi.IN_QUERY,
                description="Number of chunks to skip",
                type=openapi.TYPE_INTEGER,
                default=0,
            ),
        ],
        responses={
            200: ChunkPreviewResponseSerializer,
            404: "NaiveRag or DocumentConfig not found",
        },
    )
    def get(self, request, naive_rag_id: int, document_config_id: int):
        # Validate document config exists and belongs to naive_rag
        try:
            config = NaiveRagDocumentConfig.objects.get(
                naive_rag_document_id=document_config_id,
                naive_rag_id=naive_rag_id,
            )
        except NaiveRagDocumentConfig.DoesNotExist:
            return Response(
                {
                    "error": f"DocumentConfig {document_config_id} not found "
                    f"for NaiveRag {naive_rag_id}"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            limit = min(
                int(request.query_params.get("limit", self.DEFAULT_LIMIT)),
                self.MAX_LIMIT,
            )
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            return Response(
                {"error": "limit and offset must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Decide which chunks to return based on status
        doc_status = config.status

        if doc_status == NaiveRagDocumentConfig.NaiveRagDocumentStatus.COMPLETED:
            # Return indexed chunks
            chunks_qs = NaiveRagChunk.objects.filter(
                naive_rag_document_config_id=document_config_id
            ).order_by("chunk_index")
            total_count = chunks_qs.count()
            chunks = chunks_qs[offset : offset + limit]
            serializer = NaiveRagChunkSerializer(chunks, many=True)
        else:
            # Return preview chunks (for CHUNKED or other statuses)
            chunks_qs = NaiveRagPreviewChunk.objects.filter(
                naive_rag_document_config_id=document_config_id
            ).order_by("chunk_index")
            total_count = chunks_qs.count()
            chunks = chunks_qs[offset : offset + limit]
            serializer = NaiveRagPreviewChunkSerializer(chunks, many=True)

        return Response(
            {
                "naive_rag_id": naive_rag_id,
                "document_config_id": document_config_id,
                "status": doc_status,
                "total_chunks": total_count,
                "limit": limit,
                "offset": offset,
                "chunks": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
