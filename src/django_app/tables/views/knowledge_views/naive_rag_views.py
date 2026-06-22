import asyncio
import uuid

from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiParameter,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers as drf_serializers
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
    ChunkSearchResponseSerializer,
    ChunkSearchRequestSerializer,
    PreviewChunksByIdsRequestSerializer,
    PreviewChunksByIdsResponseSerializer,
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
from tables.utils.helpers import parse_int_csv
from tables.swagger_schemas.knowledge_schemas.naive_rag_schemas import (
    NAIVE_RAG_DOCUMENT_CONFIGS_GET,
    NAIVE_RAG_DOCUMENT_CONFIGS_CHUNK_GET,
    NAIVE_RAG_DOCUMENT_CONFIGS_PROCESS_CHUNKING_POST,
    NAIVE_RAG_DOCUMENT_CONFIG_GET,
    NAIVE_RAG_DOCUMENT_CONFIG_PUT,
    NAIVE_RAG_DOCUMENT_CONFIG_DELETE,
    NAIVE_RAG_DOCUMENT_CONFIGS_BULK_UPDATE_PUT,
    NAIVE_RAG_DOCUMENT_CONFIGS_BULK_DELETE_POST,
    NAIVE_RAG_DOCUMENT_CONFIGS_INITIALIZE_POST,
    NAIVE_RAG_GET,
    NAIVE_RAG_DELETE,
    NAIVE_RAG_COLLECTIONS_GET,
    NAIVE_RAG_COLLECTIONS_POST,
)


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

    @extend_schema(**NAIVE_RAG_COLLECTIONS_POST)
    @action(
        detail=False,
        methods=["post"],
        url_path="collections/(?P<collection_id>[^/.]+)/naive-rag",
    )
    def create_or_update(self, request, collection_id=None):
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

    @extend_schema(**NAIVE_RAG_COLLECTIONS_GET)
    @action(
        detail=False,
        methods=["get"],
        url_path="collections/(?P<collection_id>[^/.]+)/naive-rag",
    )
    def get_by_collection(self, request, collection_id=None):
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

    @extend_schema(**NAIVE_RAG_GET)
    def retrieve(self, request, pk=None):
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

    @extend_schema(**NAIVE_RAG_DELETE)
    def destroy(self, request, pk=None):
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIGS_INITIALIZE_POST)
    def initialize_configs(self, request, naive_rag_id=None):
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIGS_BULK_UPDATE_PUT)
    @action(detail=False, methods=["put"], url_path="bulk-update")
    def bulk_update(self, request, naive_rag_id=None):
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIGS_BULK_DELETE_POST)
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request, naive_rag_id=None):
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIGS_GET)
    @action(detail=False, methods=["get"])
    def list_configs(self, request, naive_rag_id=None):
        try:
            id_filter = parse_int_csv(request.query_params.get("ids"))
        except ValueError:
            return Response(
                {"error": "ids must be a comma-separated list of integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            configs = NaiveRagService.get_document_configs_for_naive_rag(
                int(naive_rag_id), document_config_ids=id_filter
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIG_GET)
    def retrieve(self, request, pk=None, naive_rag_id=None):
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIG_PUT)
    def update(self, request, pk=None, naive_rag_id=None):
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIG_DELETE)
    def destroy(self, request, pk=None, naive_rag_id=None):
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
    # Validate document config exists and belongs to naive_rag
    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIGS_PROCESS_CHUNKING_POST)
    def post(self, request, naive_rag_id: int, document_config_id: int):
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
        # Previewing a still-current index is inspection — don't flip to CHUNKING
        # (would falsely show "indexing in progress").
        if not config.is_snapshot_current():
            NaiveRagService.begin_attempt(
                config=config,
                new_status=NaiveRagDocumentConfig.NaiveRagDocumentStatus.CHUNKING,
            )

        logger.info(
            f"Starting chunking job {chunking_job_id} for config {document_config_id}"
        )
        # Publish and wait for response
        try:
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
            message = NaiveRagService.mark_config_failed_and_get_message(
                config=config,
                error_code=NaiveRagDocumentConfig.DocumentErrorCode.CHUNKING_FAILED,
                exc=e,
            )
            return Response(
                {
                    "chunking_job_id": chunking_job_id,
                    "naive_rag_id": naive_rag_id,
                    "document_config_id": document_config_id,
                    "status": "failed",
                    "chunk_count": None,
                    "message": message,
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

    @extend_schema(**NAIVE_RAG_DOCUMENT_CONFIGS_CHUNK_GET)
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


class NaiveRagChunkSearchView(APIView):
    """
    Search preview chunks of a document config by text query.

    URL: GET /naive-rag/{naive_rag_id}/document-configs/{document_config_id}/chunks/search/?q=...

    Query params:
    - q: search string (required, non-empty); matched as a case-insensitive
         substring of chunk text (internal whitespace preserved)
    - limit: max returned ids (default 100, max 500)
    - offset: how many ids to skip (default 0)

    Returns IDs of matching preview chunks (NaiveRagPreviewChunk). Frontend
    uses these ids to highlight or filter the rendered preview-chunk list.
    """

    DEFAULT_LIMIT = 100
    MAX_LIMIT = 500

    @extend_schema(
        description="Search chunk IDs of a document config by text query",
        parameters=[
            OpenApiParameter(
                name="q",
                location=OpenApiParameter.QUERY,
                description="Search query (case-insensitive substring; spaces preserved)",
                type=OpenApiTypes.STR,
                required=True,
            ),
            OpenApiParameter(
                name="limit",
                location=OpenApiParameter.QUERY,
                description="Max number of chunk IDs to return (max 500)",
                type=OpenApiTypes.INT,
                required=False,
                default=DEFAULT_LIMIT,
            ),
            OpenApiParameter(
                name="offset",
                location=OpenApiParameter.QUERY,
                description="Number of chunk IDs to skip",
                type=OpenApiTypes.INT,
                required=False,
                default=0,
            ),
        ],
        responses={
            200: ChunkSearchResponseSerializer,
            400: OpenApiResponse(description="Invalid query parameters"),
            404: OpenApiResponse(description="NaiveRag or DocumentConfig not found"),
        },
    )
    def get(self, request, naive_rag_id: int, document_config_id: int):
        serializer = ChunkSearchRequestSerializer(
            data=request.query_params,
            context={
                "default_limit": self.DEFAULT_LIMIT,
                "max_limit": self.MAX_LIMIT,
            },
        )
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data["q"]
        limit = serializer.validated_data["limit"]
        offset = serializer.validated_data["offset"]

        try:
            result = NaiveRagService.search_chunks(
                naive_rag_id=naive_rag_id,
                document_config_id=document_config_id,
                query=query,
                limit=limit,
                offset=offset,
            )
        except DocumentConfigNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("Chunk search failed")
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "naive_rag_id": naive_rag_id,
                "document_config_id": document_config_id,
                "query": query,
                "total_matches": result["total_matches"],
                "limit": limit,
                "offset": offset,
                "preview_chunk_ids": result["preview_chunk_ids"],
            },
            status=status.HTTP_200_OK,
        )


class NaiveRagPreviewChunkBulkByIdsView(APIView):
    """
    Fetch preview chunks of a document config by a list of preview_chunk_ids.

    URL: POST /naive-rag/{naive_rag_id}/document-configs/{document_config_id}/chunks/by-ids/

    Body:
        {"preview_chunk_ids": [1, 2, 3]}

    Returns the matching NaiveRagPreviewChunk objects in the same order as the
    deduplicated input ids. Ids that do not belong to the given document_config
    are silently skipped.
    """

    @extend_schema(
        description="Fetch preview chunks by a list of preview_chunk_ids",
        request=PreviewChunksByIdsRequestSerializer,
        responses={
            200: PreviewChunksByIdsResponseSerializer,
            400: OpenApiResponse(description="Invalid request body"),
            404: OpenApiResponse(description="NaiveRag or DocumentConfig not found"),
        },
    )
    def post(self, request, naive_rag_id: int, document_config_id: int):
        serializer = PreviewChunksByIdsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        preview_chunk_ids = serializer.validated_data["preview_chunk_ids"]

        try:
            chunks = NaiveRagService.get_preview_chunks_by_ids(
                naive_rag_id=naive_rag_id,
                document_config_id=document_config_id,
                preview_chunk_ids=preview_chunk_ids,
            )
        except DocumentConfigNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception("Bulk fetch of preview chunks by ids failed")
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        chunk_serializer = NaiveRagPreviewChunkSerializer(chunks, many=True)
        return Response(
            {
                "naive_rag_id": naive_rag_id,
                "document_config_id": document_config_id,
                "total": len(chunks),
                "chunks": chunk_serializer.data,
            },
            status=status.HTTP_200_OK,
        )
