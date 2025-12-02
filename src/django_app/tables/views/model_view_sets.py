from tables.models.webhook_models import WebhookTrigger
from tables.models.knowledge_models import Chunk
from django_filters import rest_framework as filters
from tables.models.crew_models import (
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    TaskMcpTools,
)
from tables.exceptions import TaskSerializerError, AgentSerializerError
from tables.models.llm_models import (
    RealtimeConfig,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.exceptions import PermissionDenied
from django_filters.rest_framework import (
    DjangoFilterBackend,
    FilterSet,
    CharFilter,
    NumberFilter,
)
from rest_framework import viewsets, mixins, status, filters as drf_filters
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from django.db.models import Prefetch
from tables.models.graph_models import (
    Condition,
    ConditionGroup,
    DecisionTableNode,
    EndNode,
    LLMNode,
    Organization,
    OrganizationUser,
    GraphOrganization,
    GraphOrganizationUser,
    WebhookTriggerNode,
)
from tables.models.realtime_models import (
    RealtimeSessionItem,
    RealtimeAgent,
    RealtimeAgentChat,
)
from tables.filters import ProviderFilter
from tables.models.tag_models import AgentTag, CrewTag, GraphTag
from tables.models.vector_models import MemoryDatabase
from tables.models.mcp_models import McpTool
from utils.logger import logger
from django.db.models import IntegerField, NOT_PROVIDED
from django.db.models.functions import Cast
from tables.serializers.model_serializers import (
    AgentReadSerializer,
    AgentWriteSerializer,
    ChunkSerializer,
    CrewTagSerializer,
    AgentTagSerializer,
    DecisionTableNodeSerializer,
    EndNodeSerializer,
    GraphLightSerializer,
    GraphTagSerializer,
    RealtimeConfigSerializer,
    RealtimeSessionItemSerializer,
    RealtimeAgentSerializer,
    RealtimeAgentChatSerializer,
    StartNodeSerializer,
    ConditionGroupSerializer,
    ConditionSerializer,
    TaskReadSerializer,
    TaskWriteSerializer,
    TaskConfiguredTools,
    TaskPythonCodeTools,
    McpToolSerializer,
    GraphFileReadSerializer,
    WebhookTriggerNodeSerializer,
    WebhookTriggerSerializer,
)
from tables.serializers.export_serializers import (
    AgentExportSerializer,
    CrewExportSerializer,
    GraphExportSerializer,
    EntityType,
)
from tables.serializers.import_serializers import (
    AgentImportSerializer,
    CrewImportSerializer,
    GraphImportSerializer,
)
from tables.serializers.copy_serializers import (
    AgentCopySerializer,
    AgentCopyDeserializer,
    CrewCopySerializer,
    CrewCopyDeserializer,
    GraphCopySerializer,
    GraphCopyDeserializer,
)
from tables.serializers.serializers import (
    UploadGraphFileSerializer,
    GraphFileUpdateSerializer,
)


from tables.models import (
    Agent,
    Task,
    TemplateAgent,
    ToolConfig,
    Tool,
    LLMConfig,
    EmbeddingModel,
    LLMModel,
    Provider,
    Crew,
    EmbeddingConfig,
    ConditionalEdge,
    CrewNode,
    Edge,
    Graph,
    GraphSessionMessage,
    PythonCode,
    PythonCodeResult,
    PythonCodeTool,
    PythonNode,
    FileExtractorNode,
    AudioTranscriptionNode,
    RealtimeModel,
    StartNode,
    ToolConfigField,
    TaskContext,
    GraphFile,
)

from tables.models import (
    AgentSessionMessage,
    TaskSessionMessage,
    UserSessionMessage,
    SourceCollection,
    DocumentMetadata,
)

from tables.serializers.model_serializers import (
    AgentSessionMessageSerializer,
    ConditionalEdgeSerializer,
    CrewNodeSerializer,
    EdgeSerializer,
    GraphSerializer,
    GraphSessionMessageSerializer,
    LLMNodeSerializer,
    MemorySerializer,
    PythonCodeResultSerializer,
    PythonCodeSerializer,
    PythonCodeToolSerializer,
    PythonNodeSerializer,
    FileExtractorNodeSerializer,
    AudioTranscriptionNodeSerializer,
    TaskSessionMessageSerializer,
    TemplateAgentSerializer,
    LLMConfigSerializer,
    ProviderSerializer,
    LLMModelSerializer,
    EmbeddingModelSerializer,
    EmbeddingConfigSerializer,
    CrewSerializer,
    ToolConfigSerializer,
    UserSessionMessageSerializer,
    RealtimeModelSerializer,
    RealtimeTranscriptionConfigSerializer,
    RealtimeTranscriptionModelSerializer,
    OrganizationSerializer,
    OrganizationUserSerializer,
    GraphOrganizationSerializer,
    GraphOrganizationUserSerializer,
)

from tables.serializers.knowledge_serializers import (
    SourceCollectionReadSerializer,
    UploadSourceCollectionSerializer,
    UpdateSourceCollectionSerializer,
    CopySourceCollectionSerializer,
    AddSourcesSerializer,
    DocumentMetadataSerializer,
)
from tables.services.redis_service import RedisService
from tables.services.copy_services import CrewCopyService, AgentCopyService
from tables.utils.mixins import ImportExportMixin, DeepCopyMixin
from tables.exceptions import BuiltInToolModificationError


redis_service = RedisService()


class BasePredefinedRestrictedViewSet(ModelViewSet):
    """
    Base ViewSet class for predefined models.
    """

    def get_queryset(self):
        if self.action in ["list", "retrieve"]:
            return self.queryset
        return self.queryset.filter(predefined=False)

    def perform_create(self, serializer):
        if serializer.validated_data.get("predefined", False):
            e = f"Attempt to create predefined {self.queryset.model.__name__.lower()}"
            logger.error(e)
            raise PermissionDenied(e)
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.predefined:
            e = f"Attempt to update predefined {self.queryset.model.__name__.lower()}"
            logger.error(e)
            raise PermissionDenied(e)
        if serializer.validated_data.get("predefined", False):
            e = f"Attempt to update predefined field in {self.queryset.model.__name__.lower()}"
            logger.error(e)
            raise PermissionDenied(e)
        serializer.save()


class TemplateAgentReadWriteViewSet(ModelViewSet):
    queryset = TemplateAgent.objects.all()
    serializer_class = TemplateAgentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = serializer_class.Meta.fields


class LLMConfigReadWriteViewSet(ModelViewSet):
    class LLMConfigFilter(filters.FilterSet):
        model_provider_id = filters.CharFilter(
            field_name="model__llm_provider__id", lookup_expr="icontains"
        )

        class Meta:
            model = LLMConfig
            fields = [
                "custom_name",
                "model",
                "is_visible",
            ]

    queryset = LLMConfig.objects.all()
    serializer_class = LLMConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = LLMConfigFilter


class ProviderReadWriteViewSet(ModelViewSet):
    queryset = Provider.objects.all()
    serializer_class = ProviderSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProviderFilter


class LLMModelReadWriteViewSet(BasePredefinedRestrictedViewSet):
    queryset = LLMModel.objects.all()
    serializer_class = LLMModelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = serializer_class.Meta.fields


class EmbeddingModelReadWriteViewSet(BasePredefinedRestrictedViewSet):
    queryset = EmbeddingModel.objects.all()
    serializer_class = EmbeddingModelSerializer
    filter_backends = [DjangoFilterBackend]

    filterset_fields = serializer_class.Meta.fields


class EmbeddingConfigReadWriteViewSet(ModelViewSet):

    class EmbeddingConfigFilter(filters.FilterSet):
        model_provider_id = filters.CharFilter(
            field_name="model__embedding_provider__id", lookup_expr="icontains"
        )

        class Meta:
            model = EmbeddingConfig
            fields = [
                "custom_name",
                "model",
                "is_visible",
            ]

    queryset = EmbeddingConfig.objects.all()
    serializer_class = EmbeddingConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = EmbeddingConfigFilter


class AgentViewSet(ModelViewSet, ImportExportMixin):
    queryset = Agent.objects.select_related("realtime_agent").prefetch_related(
        Prefetch(
            "python_code_tools",
            queryset=AgentPythonCodeTools.objects.select_related(
                "pythoncodetool__python_code"
            ),
            to_attr="prefetched_python_code_tools",
        ),
        Prefetch(
            "configured_tools",
            queryset=AgentConfiguredTools.objects.select_related(
                "toolconfig__tool"
            ).prefetch_related(
                Prefetch(
                    "toolconfig__tool__tool_fields",
                    queryset=ToolConfigField.objects.all(),
                    to_attr="prefetched_config_fields",
                )
            ),
            to_attr="prefetched_configured_tools",
        ),
        Prefetch(
            "mcp_tools",
            queryset=AgentMcpTools.objects.select_related("mcptool"),
            to_attr="prefetched_mcp_tools",
        ),
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "memory",
        "allow_delegation",
        "cache",
        "allow_code_execution",
    ]

    entity_type = EntityType.AGENT.value
    export_prefix = "agent"
    filename_attr = "role"
    serializer_response_class = AgentReadSerializer
    anget_copy_service = AgentCopyService()

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return AgentReadSerializer
        if self.action == "export":
            return AgentExportSerializer
        if self.action == "import_entity":
            return AgentImportSerializer
        return AgentWriteSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        crew_id = self.request.query_params.get("crew_id")

        if crew_id is not None:
            queryset = queryset.filter(crew__id=crew_id)

        return queryset

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "tools" in request.data:
            raise AgentSerializerError(detail="Use tool_ids instead of tools")
        write_serializer = self.get_serializer(
            instance, data=request.data, partial=False
        )
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        instance.refresh_from_db()
        read_serializer = AgentReadSerializer(
            instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "tools" in request.data:
            raise AgentSerializerError(detail="Use tool_ids instead of tools")

        write_serializer = self.get_serializer(
            instance, data=request.data, partial=True
        )
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        instance.refresh_from_db()
        read_serializer = AgentReadSerializer(
            instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="copy")
    def copy(self, request, pk: int):
        """Create a copy of an agent."""
        agent = self.get_object()

        try:
            with transaction.atomic():
                created_agent = self.agent_copy_service.copy(agent)
                serializer = self.get_serializer(created_agent)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"error": "Failed to copy agent", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CrewReadWriteViewSet(ModelViewSet, ImportExportMixin):
    queryset = Crew.objects.prefetch_related("task_set", "agents", "tags")
    serializer_class = CrewSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "description",
        "name",
        "process",
        "memory",
        "embedding_config",
        "manager_llm_config",
        "cache",
        "full_output",
        "planning",
        "planning_llm_config",
        "is_template",
    ]

    entity_type = EntityType.CREW.value
    export_prefix = "crew"
    filename_attr = "name"
    serializer_response_class = CrewSerializer

    crew_copy_service = CrewCopyService()

    def get_serializer_class(self):
        if self.action == "export":
            return CrewExportSerializer
        if self.action == "import_entity":
            return CrewImportSerializer
        return super().get_serializer_class()

    @action(detail=True, methods=["post"], url_path="copy")
    def copy(self, request, pk=None):
        """Create a copy of a crew along with its tasks and contexts."""
        crew = self.get_object()

        try:
            with transaction.atomic():
                created_crew = self.crew_copy_service.copy(crew)
                serializer = self.get_serializer(created_crew)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response(
                {"error": "Failed to copy crew", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"], url_path="save_as_project")
    def save_as_project(self, request, pk=None):
        """
        Custom action to save a template as a project.
        """
        crew = self.get_object()
        if not crew.is_template:
            return Response(
                "Project is not a template", status=status.HTTP_400_BAD_REQUEST
            )

        created_project = self.crew_copy_service.copy(crew)
        created_project.is_template = False
        created_project.save()

        serializer = self.get_serializer(created_project)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TaskReadWriteViewSet(ModelViewSet):
    queryset = Task.objects.prefetch_related(
        Prefetch(
            "task_python_code_tool_list",
            queryset=TaskPythonCodeTools.objects.select_related("tool__python_code"),
            to_attr="prefetched_python_code_tools",
        ),
        Prefetch(
            "task_context_list",
            queryset=TaskContext.objects.select_related("context"),
            to_attr="prefetched_contexts",
        ),
        Prefetch(
            "task_configured_tool_list",
            queryset=TaskConfiguredTools.objects.select_related(
                "tool__tool"
            ).prefetch_related(
                Prefetch(
                    "tool__tool__tool_fields",
                    queryset=ToolConfigField.objects.all(),
                    to_attr="prefetched_config_fields",
                )
            ),
            to_attr="prefetched_configured_tools",
        ),
        Prefetch(
            "task_mcp_tool_list",
            queryset=TaskMcpTools.objects.select_related("tool"),
            to_attr="prefetched_mcp_tools",
        ),
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "crew",
        "name",
        "agent",
        "order",
        "async_execution",
        "task_context_list",
    ]

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return TaskReadSerializer
        return TaskWriteSerializer

    def create(self, request, *args, **kwargs):
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_create(write_serializer)

        read_serializer = TaskReadSerializer(
            write_serializer.instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "tools" in request.data:
            raise TaskSerializerError(detail="Use tool_ids instead of tools")

        write_serializer = self.get_serializer(instance, data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)
        instance.refresh_from_db()

        read_serializer = TaskReadSerializer(
            instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "tools" in request.data:
            raise TaskSerializerError(detail="Use tool_ids instead of tools")

        write_serializer = self.get_serializer(
            instance, data=request.data, partial=True
        )
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)
        instance.refresh_from_db()

        read_serializer = TaskReadSerializer(
            instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_200_OK)


class ToolConfigViewSet(ModelViewSet):
    queryset = ToolConfig.objects.select_related("tool").prefetch_related(
        Prefetch(
            "tool__tool_fields",
            queryset=ToolConfigField.objects.all(),
            to_attr="prefetched_config_fields",
        )
    )
    serializer_class = ToolConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["tool", "name"]


class PythonCodeViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing PythonCode instances.
    """

    queryset = PythonCode.objects.all()
    serializer_class = PythonCodeSerializer


class PythonCodeToolViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing PythonCodeTool instances.
    Prevents modifications or deletions of built-in tools.
    """

    queryset = PythonCodeTool.objects.all()
    serializer_class = PythonCodeToolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "python_code"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.built_in:
            raise BuiltInToolModificationError()
        return super().destroy(request, *args, **kwargs)


class PythonCodeResultReadViewSet(ReadOnlyModelViewSet):
    queryset = PythonCodeResult.objects.all()
    serializer_class = PythonCodeResultSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["execution_id", "returncode"]


class GraphViewSet(viewsets.ModelViewSet, ImportExportMixin, DeepCopyMixin):
    serializer_class = GraphSerializer

    entity_type = EntityType.GRAPH.value
    export_prefix = "graph"
    filename_attr = "name"
    serializer_response_class = GraphSerializer

    copy_serializer_class = GraphCopySerializer
    copy_deserializer_class = GraphCopyDeserializer
    copy_serializer_response_class = GraphSerializer

    def get_queryset(self):
        return (
            Graph.objects.defer("metadata", "tags")
            .prefetch_related(
                Prefetch(
                    "crew_node_list", queryset=CrewNode.objects.select_related("crew")
                ),
                Prefetch(
                    "python_node_list",
                    queryset=PythonNode.objects.select_related("python_code"),
                ),
                Prefetch(
                    "file_extractor_node_list", queryset=FileExtractorNode.objects.all()
                ),
                Prefetch(
                    "audio_transcription_node_list",
                    queryset=AudioTranscriptionNode.objects.all(),
                ),
                Prefetch("edge_list", queryset=Edge.objects.all()),
                Prefetch(
                    "conditional_edge_list",
                    queryset=ConditionalEdge.objects.select_related("python_code"),
                ),
                Prefetch(
                    "llm_node_list",
                    queryset=LLMNode.objects.select_related("llm_config"),
                ),
                Prefetch(
                    "webhook_trigger_node_list",
                    queryset=WebhookTriggerNode.objects.all(),
                ),
                Prefetch(
                    "decision_table_node_list", queryset=DecisionTableNode.objects.all()
                ),
                Prefetch("end_node", queryset=EndNode.objects.all()),
            )
            .all()
        )

    def get_serializer_class(self):
        if self.action == "export":
            return GraphExportSerializer
        if self.action == "import_entity":
            return GraphImportSerializer
        return super().get_serializer_class()

    @action(detail=True, methods=["get"], url_path="files")
    def get_files(self, request, pk=None):
        graph = self.get_object()
        files = graph.uploaded_files.all()
        serializer = GraphFileReadSerializer(
            instance=files, many=True, context={"request": request}
        )
        return Response(serializer.data)


class GraphLightViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GraphLightSerializer
    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter]
    # filterset_fields = ['tags']  TODO: Uncomment when tags logic implemented
    search_fields = ["name", "description"]

    def get_queryset(self):
        return Graph.objects.prefetch_related("tags")


class CrewNodeViewSet(viewsets.ModelViewSet):
    queryset = CrewNode.objects.all()
    serializer_class = CrewNodeSerializer


class PythonNodeViewSet(viewsets.ModelViewSet):
    queryset = PythonNode.objects.all()
    serializer_class = PythonNodeSerializer


class FileExtractorNodeViewSet(viewsets.ModelViewSet):
    queryset = FileExtractorNode.objects.all()
    serializer_class = FileExtractorNodeSerializer


class AudioTranscriptionNodeViewSet(viewsets.ModelViewSet):
    queryset = AudioTranscriptionNode.objects.all()
    serializer_class = AudioTranscriptionNodeSerializer


class LLMNodeViewSet(viewsets.ModelViewSet):
    queryset = LLMNode.objects.all()
    serializer_class = LLMNodeSerializer


class EdgeViewSet(viewsets.ModelViewSet):
    queryset = Edge.objects.all()
    serializer_class = EdgeSerializer


class ConditionalEdgeViewSet(viewsets.ModelViewSet):
    queryset = ConditionalEdge.objects.all()
    serializer_class = ConditionalEdgeSerializer


class GraphSessionMessageReadOnlyViewSet(ReadOnlyModelViewSet):
    queryset = GraphSessionMessage.objects.all()
    serializer_class = GraphSessionMessageSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["session_id"]


class SourceCollectionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for SourceCollection.

    - GET: all collections.
    - GET: collection by id.
    - POST: create a collection with multiple file uploads.
    - PATCH: Update allowed fields (collection_name).
    - DELETE: Delete a collection (and its related documents).

    Custom action:
    - PATCH: /add-sources/ endpoint to add new documents to an existing collection.
    """

    http_method_names = ["get", "post", "patch", "delete"]

    queryset = SourceCollection.objects.prefetch_related("document_metadata")

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return SourceCollectionReadSerializer
        elif self.action in ["partial_update", "update"]:
            return UpdateSourceCollectionSerializer
        return UploadSourceCollectionSerializer

    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            collection = serializer.save()
        redis_service.publish_source_collection(collection_id=collection.pk)
        return Response(
            SourceCollectionReadSerializer(collection).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        """
        Only allow updating collection_name.
        """
        instance = self.get_object()
        serializer = UpdateSourceCollectionSerializer(
            instance, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"message": "Collection deleted successfully"},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["patch"], url_path="add-sources")
    def add_sources(self, request, pk=None):
        """
        Custom action to add new documents (files) to an existing collection.
        Accepts multipart/form-data with a "files" field.
        """
        collection = self.get_object()
        serializer = AddSourcesSerializer(data=request.data)
        if serializer.is_valid():
            with transaction.atomic():
                serializer.create_documents(collection)

            read_serializer = SourceCollectionReadSerializer(collection)
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CopySourceCollectionViewSet(viewsets.ModelViewSet):
    http_method_names = ["post"]

    queryset = SourceCollection.objects.all()
    serializer_class = CopySourceCollectionSerializer

    def create(self, request):
        with transaction.atomic():
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            collection = serializer.save()

        return Response(
            SourceCollectionReadSerializer(collection).data,
            status=status.HTTP_201_CREATED,
        )


class DocumentMetadataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DocumentMetadata.objects.select_related("source_collection")
    serializer_class = DocumentMetadataSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        collection: SourceCollection = instance.source_collection
        instance.delete()

        collection.update_collection_status()

        return Response(
            {
                "message": f"Source '{instance.file_name}' from colection '{instance.source_collection.collection_name}' deleted successfully"
            },
            status=status.HTTP_200_OK,
        )


class MemoryFilter(FilterSet):
    run_id = NumberFilter(method="filter_run_id")
    agent_id = CharFilter(field_name="payload__agent_id", lookup_expr="exact")
    user_id = CharFilter(field_name="payload__user_id", lookup_expr="exact")
    type = CharFilter(field_name="payload__type", lookup_expr="exact")

    class Meta:
        model = MemoryDatabase
        fields = ["run_id", "agent_id", "user_id", "type"]

    def filter_run_id(self, queryset, name, value):
        return queryset.annotate(
            run_id_int=Cast("payload__run_id", IntegerField())
        ).filter(run_id_int=value)


class MemoryViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):

    queryset = MemoryDatabase.objects.all()
    serializer_class = MemorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = MemoryFilter


class CrewTagViewSet(viewsets.ModelViewSet):
    queryset = CrewTag.objects.all()
    serializer_class = CrewTagSerializer


class AgentTagViewSet(viewsets.ModelViewSet):
    queryset = AgentTag.objects.all()
    serializer_class = AgentTagSerializer


class GraphTagViewSet(viewsets.ModelViewSet):
    queryset = GraphTag.objects.all()
    serializer_class = GraphTagSerializer


class RealtimeModelViewSet(viewsets.ModelViewSet):
    queryset = RealtimeModel.objects.all()
    serializer_class = RealtimeModelSerializer


class RealtimeConfigModelViewSet(viewsets.ModelViewSet):
    class RealtimeConfigFilter(filters.FilterSet):
        model_provider_id = filters.CharFilter(
            field_name="realtime_model__provider__id", lookup_expr="icontains"
        )

        class Meta:
            model = RealtimeConfig
            fields = [
                "custom_name",
                "realtime_model",
            ]

    queryset = RealtimeConfig.objects.all()
    serializer_class = RealtimeConfigSerializer

    filter_backends = [DjangoFilterBackend]
    filterset_class = RealtimeConfigFilter


class RealtimeTranscriptionModelViewSet(viewsets.ModelViewSet):
    queryset = RealtimeTranscriptionModel.objects.all()
    serializer_class = RealtimeTranscriptionModelSerializer


class RealtimeTranscriptionConfigModelViewSet(viewsets.ModelViewSet):
    class RealtimeTranscriptionConfigFilter(filters.FilterSet):
        model_provider_id = filters.CharFilter(
            field_name="realtime_transcription_model__provider__id",
            lookup_expr="icontains",
        )

        class Meta:
            model = RealtimeTranscriptionConfig
            fields = [
                "custom_name",
                "realtime_transcription_model",
            ]

    queryset = RealtimeTranscriptionConfig.objects.all()
    serializer_class = RealtimeTranscriptionConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = RealtimeTranscriptionConfigFilter


class RealtimeSessionItemViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RealtimeSessionItem.objects.all()
    serializer_class = RealtimeSessionItemSerializer


class RealtimeAgentViewSet(viewsets.ModelViewSet):
    queryset = RealtimeAgent.objects.all()
    serializer_class = RealtimeAgentSerializer


class RealtimeAgentChatViewSet(ReadOnlyModelViewSet):
    """
    ViewSet for reading and deleting RealtimeAgentChat instances.
    """

    queryset = RealtimeAgentChat.objects.all()
    serializer_class = RealtimeAgentChatSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["rt_agent"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(
            {"detail": "Deleted successfully"}, status=status.HTTP_204_NO_CONTENT
        )


class StartNodeModelViewSet(viewsets.ModelViewSet):
    queryset = StartNode.objects.all()
    serializer_class = StartNodeSerializer


class EndNodeModelViewSet(viewsets.ModelViewSet):
    queryset = EndNode.objects.all()
    serializer_class = EndNodeSerializer


class ConditionGroupModelViewSet(viewsets.ModelViewSet):
    queryset = ConditionGroup.objects.all()
    serializer_class = ConditionGroupSerializer


class ConditionModelViewSet(viewsets.ModelViewSet):
    queryset = Condition.objects.all()
    serializer_class = ConditionSerializer


class DecisionTableNodeModelViewSet(viewsets.ModelViewSet):
    queryset = DecisionTableNode.objects.all()
    serializer_class = DecisionTableNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph"]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Create a DecisionTableNode along with nested ConditionGroups and Conditions.
        """
        node, _ = self._create_or_update_node(data=request.data)
        return Response(self.get_serializer(node).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """
        Update a DecisionTableNode along with nested ConditionGroups and Conditions.
        Supports partial updates (PATCH).
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        node, _ = self._create_or_update_node(
            data=request.data, instance=instance, partial=partial
        )
        return Response(self.get_serializer(node).data, status=status.HTTP_200_OK)

    def _create_or_update_node(self, data, instance=None, partial=False):
        """
        Create or update a DecisionTableNode with nested groups.
        """
        data = data.copy()
        condition_groups_data = data.pop("condition_groups", None)

        # Serialize and save the main DecisionTableNode
        node_serializer = self.get_serializer(instance, data=data, partial=partial)
        node_serializer.is_valid(raise_exception=True)
        node = node_serializer.save()

        # If PATCH and no condition_groups provided, skip nested updates
        if partial and condition_groups_data is None:
            return node, None

        # Delete existing groups and conditions (for update)
        if instance:
            self._delete_existing_groups(node)

        # Create new groups and conditions
        if condition_groups_data:
            self._create_condition_groups(node, condition_groups_data)

        return node, condition_groups_data

    def _delete_existing_groups(self, node: DecisionTableNode):
        """
        Delete all ConditionGroups and related Conditions for a given DecisionTableNode.
        """
        Condition.objects.filter(condition_group__decision_table_node=node).delete()
        ConditionGroup.objects.filter(decision_table_node=node).delete()

    def _create_condition_groups(
        self, node: DecisionTableNode, groups_data: list[dict]
    ):
        """
        Create ConditionGroups and nested Conditions for a DecisionTableNode.
        Uses bulk_create for efficiency.
        """
        groups_to_create = []
        conditions_to_create = []

        # Prepare group objects
        for group_data in groups_data:
            copy_grop_data = group_data.copy()
            copy_grop_data.pop("conditions")
            groups_to_create.append(
                ConditionGroup(decision_table_node=node, **copy_grop_data)
            )
            # Conditions will be mapped after saving groups

        # Save groups in bulk
        created_groups = ConditionGroup.objects.bulk_create(groups_to_create)

        # Map and prepare condition objects
        for group, group_data in zip(created_groups, groups_data):
            for cond_data in group_data.get("conditions", []):
                conditions_to_create.append(
                    Condition(condition_group=group, **cond_data)
                )

        # Save conditions in bulk
        if conditions_to_create:
            Condition.objects.bulk_create(conditions_to_create)


class McpToolViewSet(viewsets.ModelViewSet):
    queryset = McpTool.objects.all()
    serializer_class = McpToolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "tool_name"]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data.copy()
        for field in self.serializer_class.Meta.model._meta.get_fields():
            if field.concrete and field.name not in data:
                default = getattr(field, "default", None)
                data[field.name] = default if default != NOT_PROVIDED else None
        serializer = self.get_serializer(instance, data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class GraphFileViewSet(ModelViewSet):
    queryset = GraphFile.objects.all()
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "put", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return GraphFileReadSerializer
        if self.action in ["update"]:
            return GraphFileUpdateSerializer
        return UploadGraphFileSerializer

    def create(self, request, *args, **kwargs):
        graph = request.data.get("graph")
        if not graph:
            return Response(
                {"message": "Graph is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        files = {k: v for k, v in request.FILES.items()}
        if not files:
            return Response(
                {"files": "This field is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        if isinstance(graph, list):
            graph = graph[0]

        data = {"graph": graph, "files": files}
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        instances = serializer.save()

        serializer = GraphFileReadSerializer(
            instance=instances, many=True, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        data = {}
        for key, file in request.FILES.items():
            data["domain_key"] = key
            data["file"] = file

        if not data:
            return Response(
                {"file": "This field is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        instance = self.get_object()

        serializer_class = self.get_serializer_class()
        serializer = serializer_class(
            instance=instance, data=data, context={"graph": instance.graph}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({"detail": "File updated successfully."})


class ChunkViewSet(ReadOnlyModelViewSet):
    queryset = Chunk.objects.all()
    serializer_class = ChunkSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["document_id"]


class OrganizationViewSet(viewsets.ModelViewSet):

    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer


class OrganizationUserViewSet(viewsets.ModelViewSet):

    queryset = OrganizationUser.objects.all()
    serializer_class = OrganizationUserSerializer


class GraphOrganizationViewSet(viewsets.ModelViewSet):

    queryset = GraphOrganization.objects.all()
    serializer_class = GraphOrganizationSerializer


class GraphOrganizationUserViewSet(viewsets.ReadOnlyModelViewSet):

    queryset = GraphOrganizationUser.objects.all()
    serializer_class = GraphOrganizationUserSerializer


class WebhookTriggerNodeViewSet(viewsets.ModelViewSet):
    queryset = WebhookTriggerNode.objects.all()
    serializer_class = WebhookTriggerNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph", "node_name", "webhook_trigger__path"]


class WebhookTriggerViewSet(viewsets.ModelViewSet):
    queryset = WebhookTrigger.objects.all()
    serializer_class = WebhookTriggerSerializer
    filter_backends = [DjangoFilterBackend]
