from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse

from rest_framework.permissions import IsAuthenticated

from tables.models import SourceCollection
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tables.models.knowledge_models import GraphRag
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.graph_rag_serializers import (
    GraphRagSerializer,
    GraphRagCreateSerializer,
    GraphRagDetailSerializer,
    GraphRagIndexConfigUpdateSerializer,
    GraphRagDocumentIdsSerializer,
    GraphRagDocumentListSerializer,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.views.mixins import OrgScopedServiceViewSetMixin
from tables.services.rbac.permissions import HasOrgPermission
from tables.services.rbac.permission_action_map import DEFAULT_ACTION_MAP

from tables.exceptions import (
    RagException,
    GraphRagNotFoundException,
    GraphRagDocumentNotFoundException,
    EmbedderNotFoundException,
    LLMConfigNotFoundException,
    CollectionNotFoundException,
    InvalidGraphRagParametersException,
    InvalidFieldType,
)


# ORM path from a GraphRag up to the owning collection's org.
_GRAPH_RAG_ORG_PATH = "base_rag_type__source_collection__org_id"


class GraphRagViewSet(OrgScopedServiceViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for GraphRag operations.

    Endpoints:
    - POST /graph-rag/collections/{collection_id}/graph-rag/ - Create GraphRag (auto-adds all docs)
    - GET /graph-rag/collections/{collection_id}/graph-rag/ - Get GraphRag for collection
    - GET /graph-rag/{id}/ - Get GraphRag details
    - DELETE /graph-rag/{id}/ - Delete GraphRag
    - PUT /graph-rag/{id}/index-config/ - Update index configuration
    - POST /graph-rag/{id}/documents/bulk-delete/ - Remove documents (batch)
    - GET /graph-rag/{id}/documents/list/ - List documents
    - POST /graph-rag/{id}/documents/initialize/ - Re-add all docs from collection
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.KNOWLEDGE_SOURCES
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "create_or_update": Permission.CREATE,
        "get_by_collection": Permission.READ,
        "update_index_config": Permission.UPDATE,
        "remove_documents": Permission.UPDATE,
        "delete_document": Permission.UPDATE,
        "list_documents": Permission.READ,
        "initialize_documents": Permission.UPDATE,
    }

    queryset = GraphRag.objects.all()
    serializer_class = GraphRagSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GraphRag.objects.none()
        return super().get_queryset()

    def _assert_graph_rag_in_active_org(self, pk):
        self.get_in_active_org_or_404(GraphRag, int(pk), _GRAPH_RAG_ORG_PATH)

    def get_serializer_class(self):
        if self.action == "create_or_update":
            return GraphRagCreateSerializer
        elif self.action == "retrieve":
            return GraphRagDetailSerializer
        elif self.action == "update_index_config":
            return GraphRagIndexConfigUpdateSerializer
        elif self.action == "remove_documents":
            return GraphRagDocumentIdsSerializer
        return GraphRagSerializer

    @action(
        detail=False,
        methods=["post"],
        url_path="collections/(?P<collection_id>[^/.]+)/graph-rag",
    )
    def create_or_update(self, request, collection_id=None):
        """
        Create new GraphRag or update existing one for a collection.

        URL: POST /graph-rag/collections/{collection_id}/graph-rag/

        Body:
        {
            "embedder_id": 1,
            "llm_id": 1
        }
        """
        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        # The collection must live in the active org (404 otherwise).
        self.get_in_active_org_or_404(SourceCollection, collection_id)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        embedder_id = serializer.validated_data["embedder_id"]
        llm_id = serializer.validated_data["llm_id"]
        # Referenced configs must belong to the active org (404 like a missing pk).
        self.get_in_active_org_or_404(EmbeddingConfig, embedder_id)
        self.get_in_active_org_or_404(LLMConfig, llm_id)

        try:
            graph_rag = GraphRagService.create_or_update_graph_rag(
                collection_id=collection_id,
                embedder_id=embedder_id,
                llm_id=llm_id,
            )

            response_serializer = GraphRagDetailSerializer(graph_rag)

            return Response(
                {
                    "message": "GraphRag configured successfully",
                    "graph_rag": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except CollectionNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except EmbedderNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except LLMConfigNotFoundException as e:
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
        url_path="collections/(?P<collection_id>[^/.]+)/graph-rag",
    )
    def get_by_collection(self, request, collection_id=None):
        """
        Get GraphRag for a collection.

        URL: GET /graph-rag/collections/{collection_id}/graph-rag/
        """
        try:
            collection_id = int(collection_id)
        except (ValueError, TypeError):
            raise InvalidFieldType("collection_id", collection_id)

        self.get_in_active_org_or_404(SourceCollection, collection_id)

        try:
            graph_rag = GraphRagService.get_or_none_graph_rag_by_collection(
                collection_id
            )

            if not graph_rag:
                return Response(
                    {"error": f"GraphRag not found for collection {collection_id}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = GraphRagDetailSerializer(graph_rag)
            return Response(serializer.data)

        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None):
        """
        Get detailed GraphRag info including index config and documents.

        URL: GET /graph-rag/{id}/
        """
        self._assert_graph_rag_in_active_org(pk)
        try:
            graph_rag = GraphRagService.get_graph_rag(int(pk))

            serializer = GraphRagDetailSerializer(graph_rag)
            return Response(serializer.data)

        except GraphRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def destroy(self, request, pk=None):
        """
        Delete GraphRag and all its configurations.

        URL: DELETE /graph-rag/{id}/
        """
        self._assert_graph_rag_in_active_org(pk)
        try:
            result = GraphRagService.delete_graph_rag(int(pk))

            return Response(
                {"message": "GraphRag deleted successfully", **result},
                status=status.HTTP_200_OK,
            )

        except GraphRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["put"], url_path="index-config")
    def update_index_config(self, request, pk=None):
        """
        Update index configuration for GraphRag.
        Updates all nested configs (input, chunking, extract_graph, cluster_graph) in one request.

        URL: PUT /graph-rag/{id}/index-config/

        Body (all fields optional, at least one required):
        {
            "file_type": "text",
            "chunk_size": 1200,
            "chunk_overlap": 100,
            "chunk_strategy": "tokens",
            "entity_types": ["organization", "person", "geo", "event"],
            "max_gleanings": 1,
            "max_cluster_size": 10
        }
        """
        self._assert_graph_rag_in_active_org(pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            graph_rag = GraphRagService.update_index_config(
                graph_rag_id=int(pk),
                data=serializer.validated_data,
            )

            response_serializer = GraphRagDetailSerializer(graph_rag)

            return Response(
                {
                    "message": "Index configuration updated successfully",
                    "graph_rag": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except GraphRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except InvalidGraphRagParametersException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"], url_path="documents/bulk-delete")
    def remove_documents(self, request, pk=None):
        """
        Batch remove documents from GraphRag.

        URL: POST /graph-rag/{id}/documents/bulk-delete/

        Body:
        {
            "document_ids": [1, 2, 3]
        }
        """
        self._assert_graph_rag_in_active_org(pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document_ids = serializer.validated_data["document_ids"]

        try:
            result = GraphRagService.remove_documents_from_graph_rag(
                graph_rag_id=int(pk),
                document_ids=document_ids,
            )

            return Response(
                {
                    "message": f"Removed {result['removed_count']} document(s) from GraphRag",
                    **result,
                },
                status=status.HTTP_200_OK,
            )

        except GraphRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=True,
        methods=["delete"],
        url_path="documents/(?P<document_id>[^/.]+)",
    )
    def delete_document(self, request, pk=None, document_id=None):
        """
        Remove a single document from GraphRag.

        URL: DELETE /graph-rag/{id}/documents/{document_id}/
        """
        self._assert_graph_rag_in_active_org(pk)
        try:
            result = GraphRagService.delete_document(
                graph_rag_id=int(pk),
                document_id=int(document_id),
            )

            return Response(
                {
                    "message": f"Document {result['document_id']} removed from GraphRag",
                    **result,
                },
                status=status.HTTP_200_OK,
            )

        except GraphRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except GraphRagDocumentNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"], url_path="documents/list")
    def list_documents(self, request, pk=None):
        """
        List all documents in GraphRag.

        URL: GET /graph-rag/{id}/documents/list/
        """
        self._assert_graph_rag_in_active_org(pk)
        try:
            documents = GraphRagService.get_documents_for_graph_rag(int(pk))
            serializer = GraphRagDocumentListSerializer(documents, many=True)
            return Response(
                {
                    "graph_rag_id": pk,
                    "total_documents": len(documents),
                    "documents": serializer.data,
                }
            )
        except GraphRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="All documents initialized"),
            404: OpenApiResponse(description="GraphRag not found"),
            500: OpenApiResponse(description="Internal server error"),
        },
    )
    def initialize_documents(self, request, pk=None):
        """
        Initialize GraphRag with all documents from collection.
        Adds all documents from the source collection that aren't already linked.

        URL: POST /graph-rag/{id}/documents/initialize/
        """
        self._assert_graph_rag_in_active_org(pk)
        try:
            result = GraphRagService.init_documents_from_collection(int(pk))

            message = (
                f"Initialized {result['added_count']} document(s)"
                if result["added_count"] > 0
                else "All documents already linked"
            )

            return Response(
                {
                    "message": message,
                    **result,
                },
                status=status.HTTP_200_OK,
            )

        except GraphRagNotFoundException as e:
            return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except RagException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
