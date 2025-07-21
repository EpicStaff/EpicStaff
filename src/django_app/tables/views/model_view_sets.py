from django_filters import rest_framework as filters
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
from django.db import transaction
from django.db.models import Prefetch
from tables.models.graph_models import (
    Condition,
    ConditionGroup,
    DecisionTableNode,
    LLMNode,
)
from tables.models.realtime_models import (
    RealtimeSessionItem,
    RealtimeAgent,
    RealtimeAgentChat,
)
from tables.models.tag_models import AgentTag, CrewTag, GraphTag
from tables.models.vector_models import MemoryDatabase
from utils.logger import logger
from django.db.models import IntegerField
from django.db.models.functions import Cast
from tables.serializers.model_serializers import (
    AgentReadSerializer,
    AgentWriteSerializer,
    CrewTagSerializer,
    AgentTagSerializer,
    DecisionTableNodeSerializer,
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
)


from tables.models import (
    Agent,
    Task,
    TemplateAgent,
    ToolConfig,
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
    RealtimeModel,
    StartNode,
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
    filterset_fields = ["name"]


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


class AgentViewSet(ModelViewSet):
    queryset = Agent.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "memory",
        "allow_delegation",
        "cache",
        "allow_code_execution",
    ]

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return AgentReadSerializer
        return AgentWriteSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        crew_id = self.request.query_params.get("crew_id")

        if crew_id is not None:
            queryset = queryset.filter(crew__id=crew_id)

        return queryset

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        write_serializer = self.get_serializer(instance, data=request.data, partial=False)
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        # Use AgentReadSerializer for the response
        read_serializer = AgentReadSerializer(instance, context=self.get_serializer_context())
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        write_serializer = self.get_serializer(instance, data=request.data, partial=True)
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        read_serializer = AgentReadSerializer(instance, context=self.get_serializer_context())
        return Response(read_serializer.data, status=status.HTTP_200_OK)

class CrewReadWriteViewSet(ModelViewSet):
    queryset = Crew.objects.all()
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
    ]


class TaskReadWriteViewSet(ModelViewSet):
    queryset = Task.objects.all()
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

        read_serializer = TaskReadSerializer(write_serializer.instance, context=self.get_serializer_context())
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        write_serializer = self.get_serializer(instance, data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        read_serializer = TaskReadSerializer(instance, context=self.get_serializer_context())
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        write_serializer = self.get_serializer(instance, data=request.data, partial=True)
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        read_serializer = TaskReadSerializer(instance, context=self.get_serializer_context())
        return Response(read_serializer.data, status=status.HTTP_200_OK)


class ToolConfigViewSet(ModelViewSet):
    queryset = ToolConfig.objects.all()
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
    """

    queryset = PythonCodeTool.objects.all()
    serializer_class = PythonCodeToolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "python_code"]


class PythonCodeResultReadViewSet(ReadOnlyModelViewSet):
    queryset = PythonCodeResult.objects.all()
    serializer_class = PythonCodeResultSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["execution_id", "returncode"]


class GraphViewSet(viewsets.ModelViewSet):
    serializer_class = GraphSerializer

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
                    "decision_table_node_list", queryset=DecisionTableNode.objects.all()
                ),
            )
            .all()
        )


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

    queryset = SourceCollection.objects.all()

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

            redis_service.publish_source_collection(
                collection_id=collection.collection_id
            )
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

                redis_service.publish_add_source(collection_id=collection.collection_id)

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

            redis_service.publish_source_collection(
                collection_id=collection.collection_id
            )
        return Response(
            SourceCollectionReadSerializer(collection).data,
            status=status.HTTP_201_CREATED,
        )


class DocumentMetadataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DocumentMetadata.objects.all()
    serializer_class = DocumentMetadataSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
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
        # Extract nested data
        condition_groups_data = request.data.pop("condition_groups", [])

        # Create the DecisionTableNode
        node_serializer = self.get_serializer(data=request.data)
        node_serializer.is_valid(raise_exception=True)
        node = node_serializer.save()

        # Create each ConditionGroup
        for group_data in condition_groups_data:
            conditions_data = group_data.pop("conditions", [])
            group_data["decision_table_node"] = node.id
            group_serializer = ConditionGroupSerializer(data=group_data)
            group_serializer.is_valid(raise_exception=True)
            group = group_serializer.save()

            # Create each Condition
            for condition_data in conditions_data:
                condition_data["condition_group"] = group.id
                condition_serializer = ConditionSerializer(data=condition_data)
                condition_serializer.is_valid(raise_exception=True)
                condition_serializer.save()

        return Response(self.get_serializer(node).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        condition_groups_data = request.data.pop("condition_groups", [])

        # Update the DecisionTableNode instance
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        node = serializer.save()

        # Delete existing condition groups and conditions
        Condition.objects.filter(condition_group__decision_table_node=node).delete()
        ConditionGroup.objects.filter(decision_table_node=node).delete()

        # Recreate condition groups and conditions
        for group_data in condition_groups_data:
            conditions_data = group_data.pop("conditions", [])
            group_data["decision_table_node"] = node.id
            group_serializer = ConditionGroupSerializer(data=group_data)
            group_serializer.is_valid(raise_exception=True)
            group = group_serializer.save()

            for condition_data in conditions_data:
                condition_data["condition_group"] = group.id
                condition_serializer = ConditionSerializer(data=condition_data)
                condition_serializer.is_valid(raise_exception=True)
                condition_serializer.save()

        return Response(self.get_serializer(node).data)
