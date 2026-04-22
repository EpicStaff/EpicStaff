import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import NOT_PROVIDED, IntegerField, Prefetch
from django.db.models.functions import Cast
from django_filters import rest_framework as filters
from django_filters.rest_framework import (
    CharFilter,
    DjangoFilterBackend,
    FilterSet,
    NumberFilter,
)
from rest_framework import filters as drf_filters
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from tables.exceptions import (
    AgentSerializerError,
    BuiltInToolModificationError,
    BulkSaveValidationError,
    TaskSerializerError,
)
from tables.serializers.graph_bulk_save_serializers import GraphBulkSaveInputSerializer
from tables.services.graph_bulk_save_service import GraphBulkSaveService

from tables.import_export.enums import EntityType
from tables.models import (
    Agent,
    AudioTranscriptionNode,
    CodeAgentNode,
    ConditionalEdge,
    Crew,
    CrewNode,
    Edge,
    EmbeddingConfig,
    EmbeddingModel,
    FileExtractorNode,
    Graph,
    GraphSessionMessage,
    LLMConfig,
    LLMModel,
    Provider,
    PythonCode,
    PythonCodeResult,
    PythonCodeTool,
    PythonNode,
    RealtimeModel,
    StartNode,
    SubGraphNode,
    Task,
    TaskContext,
    TemplateAgent,
    ToolConfig,
    ToolConfigField,
)
from tables.models.crew_models import (
    AgentConfiguredTools,
    AgentMcpTools,
    AgentPythonCodeTools,
    AgentPythonCodeToolConfigs,
    TaskMcpTools,
    TaskPythonCodeToolConfigs,
)
from tables.exceptions import (
    TaskSerializerError,
    AgentSerializerError,
)
from tables.models.llm_models import (
    RealtimeConfig,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from tables.swagger_schemas.graph_bulk_save_schema import (
    SAVE_FLOW_SWAGGER as _SAVE_FLOW_SWAGGER,
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
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    Condition,
    ConditionGroup,
    DecisionTableNode,
    EndNode,
    GraphOrganization,
    GraphOrganizationUser,
    LLMNode,
    GraphNote,
    Organization,
    OrganizationUser,
    TelegramTriggerNode,
    TelegramTriggerNodeField,
    WebhookTriggerNode,
)
from tables.models.llm_models import (
    RealtimeConfig,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.knowledge_models.naive_rag_models import AgentNaiveRag
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeToolConfig, PythonCodeToolConfigField
from tables.models.realtime_models import (
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeSessionItem,
)
from tables.filters import (
    EmbeddingModelFilter,
    LabelFilterBackend,
    LLMModelFilter,
    ProviderFilter,
)
from tables.utils.helpers import natural_sort_key
from tables.models.tag_models import AgentTag, CrewTag, GraphTag
from tables.models.label_models import Label
from tables.models.vector_models import MemoryDatabase
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    VoiceSettings,
    WebhookTrigger,
)
from tables.services.copy_services import (
    AgentCopyService,
    CrewCopyService,
    GraphCopyService,
    McpToolCopyService,
    PythonCodeToolCopyService,
)
from tables.views.mixins import CopyActionMixin
from tables.serializers.model_serializers import (
    AgentReadSerializer,
    ClassificationDecisionTableNodeSerializer,
    AgentTagSerializer,
    AgentWriteSerializer,
    AudioTranscriptionNodeSerializer,
    CodeAgentNodeSerializer,
    ConditionalEdgeSerializer,
    GraphNoteSerializer,
    ConditionGroupSerializer,
    ConditionSerializer,
    CrewNodeSerializer,
    CrewSerializer,
    CrewTagSerializer,
    DecisionTableNodeSerializer,
    EdgeSerializer,
    EmbeddingConfigSerializer,
    EmbeddingModelSerializer,
    EndNodeSerializer,
    FileExtractorNodeSerializer,
    GraphLightSerializer,
    GraphOrganizationSerializer,
    GraphOrganizationUserSerializer,
    GraphSerializer,
    GraphSessionMessageSerializer,
    GraphTagSerializer,
    LabelSerializer,
    LLMConfigSerializer,
    LLMModelSerializer,
    LLMNodeSerializer,
    McpToolSerializer,
    MemorySerializer,
    NgrokWebhookConfigModelSerializer,
    OrganizationSerializer,
    OrganizationUserSerializer,
    ProviderSerializer,
    PythonCodeResultSerializer,
    PythonCodeSerializer,
    PythonCodeToolConfigFieldSerializer,
    PythonCodeToolConfigSerializer,
    PythonCodeToolSerializer,
    PythonNodeSerializer,
    RealtimeAgentChatSerializer,
    RealtimeAgentSerializer,
    RealtimeConfigSerializer,
    RealtimeModelSerializer,
    RealtimeSessionItemSerializer,
    RealtimeTranscriptionConfigSerializer,
    RealtimeTranscriptionModelSerializer,
    StartNodeSerializer,
    SubGraphNodeSerializer,
    TaskConfiguredTools,
    TaskPythonCodeTools,
    TaskReadSerializer,
    TaskWriteSerializer,
    TemplateAgentSerializer,
    ToolConfigSerializer,
    VoiceSettingsSerializer,
    WebhookTriggerNodeSerializer,
    WebhookTriggerSerializer,
)
from tables.serializers.serializers import (
    BulkExportSerializer,
    ImportRequestSerializer,
)
from tables.serializers.telegram_trigger_serializers import (
    TelegramTriggerNodeFieldSerializer,
    TelegramTriggerNodeSerializer,
)
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.services.import_export_service import ViewSetImportExportService
from tables.services.redis_service import RedisService
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from utils.logger import logger

redis_service = RedisService()


class BasePredefinedRestrictedViewSet(ModelViewSet):
    """
    Base ViewSet class for predefined models.
    Allows updating non-critical fields of predefined objects.
    Prevents deletion of predefined objects.
    """

    def get_queryset(self):
        if self.action == "destroy":
            return self.queryset.filter(predefined=False)

        return self.queryset

    def perform_create(self, serializer):
        if serializer.validated_data.get("predefined", False):
            e = f"Attempt to create predefined {self.queryset.model.__name__.lower()}"
            logger.error(e)
            raise PermissionDenied(e)
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        validated_data = serializer.validated_data

        if instance.predefined:
            # Should not be able to change name
            if "name" in validated_data and validated_data["name"] != instance.name:
                e = f"Cannot change the name of a predefined {self.queryset.model.__name__.lower()}"
                logger.warning(e)
                raise ValidationError({"name": e})

            # Should not be able to remove predefined
            if "predefined" in validated_data and validated_data["predefined"] is False:
                e = "Cannot unset predefined status for this object"
                logger.warning(e)
                raise ValidationError({"predefined": e})

        else:
            if validated_data.get("predefined", False):
                e = f"Attempt to set predefined=True for custom {self.queryset.model.__name__.lower()}"
                logger.error(e)
                raise PermissionDenied(e)

        serializer.save()

    def perform_destroy(self, instance):
        if instance.predefined:
            e = f"Attempt to delete predefined {self.queryset.model.__name__.lower()}"
            logger.error(e)
            raise PermissionDenied(e)
        instance.delete()


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
    queryset = LLMModel.objects.select_related("llm_provider").prefetch_related("tags")
    serializer_class = LLMModelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = LLMModelFilter


class EmbeddingModelReadWriteViewSet(BasePredefinedRestrictedViewSet):
    queryset = EmbeddingModel.objects.select_related(
        "embedding_provider"
    ).prefetch_related("tags")
    serializer_class = EmbeddingModelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = EmbeddingModelFilter


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


class AgentViewSet(CopyActionMixin, ModelViewSet):
    copy_service_class = AgentCopyService
    copy_serializer_class = AgentReadSerializer

    queryset = Agent.objects.select_related(
        "realtime_agent",
        "naive_search_config",
    ).prefetch_related(
        Prefetch(
            "python_code_tools",
            queryset=AgentPythonCodeTools.objects.select_related(
                "pythoncodetool__python_code"
            ).prefetch_related(
                Prefetch(
                    "pythoncodetool__tool_fields",
                    queryset=PythonCodeToolConfigField.objects.all(),
                )
            ),
            to_attr="prefetched_python_code_tools",
        ),
        Prefetch(
            "python_code_tool_configs",
            queryset=AgentPythonCodeToolConfigs.objects.select_related(
                "pythoncodetoolconfig__tool__python_code"
            ),
            to_attr="prefetched_python_code_tool_configs",
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
        Prefetch(
            "agent_naive_rags",
            queryset=AgentNaiveRag.objects.select_related("naive_rag"),
            to_attr="prefetched_agent_naive_rags",
        ),
    )
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "memory",
        "allow_delegation",
        "cache",
        "allow_code_execution",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.AGENT, export_prefix="agent", filename_attr="role"
        )

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return AgentReadSerializer
        return AgentWriteSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        crew_id = self.request.query_params.get("crew_id")

        if crew_id is not None:
            queryset = queryset.filter(crew__id=crew_id)

        if self.request.query_params.get("has_realtime_config") == "true":
            queryset = queryset.filter(
                realtime_agent__isnull=False,
                realtime_agent__realtime_config__isnull=False,
            )

        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Create agent and return response with AgentReadSerializer."""
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_create(write_serializer)

        # Return response using read serializer to include rag and search_configs
        read_serializer = AgentReadSerializer(
            write_serializer.instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
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

    @transaction.atomic
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

    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(self.get_object())

    @action(detail=False, methods=["post"], url_path="import")
    def import_entity(self, request):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)

        data = self.import_export_service.import_entity(
            file_serializer.validated_data["file"]
        )
        return Response(data, status=status.HTTP_200_OK)


class CrewReadWriteViewSet(CopyActionMixin, ModelViewSet):
    copy_service_class = CrewCopyService
    copy_serializer_class = CrewSerializer

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
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.CREW, export_prefix="crew", filename_attr="name"
        )

    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(self.get_object())

    @action(detail=False, methods=["post"], url_path="import")
    def import_entity(self, request):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)

        data = self.import_export_service.import_entity(
            file_serializer.validated_data["file"]
        )
        return Response(data, status=status.HTTP_200_OK)


class TaskReadWriteViewSet(ModelViewSet):
    queryset = Task.objects.prefetch_related(
        Prefetch(
            "task_python_code_tool_list",
            queryset=TaskPythonCodeTools.objects.select_related(
                "tool__python_code"
            ).prefetch_related("tool__tool_fields"),
        ),
        Prefetch(
            "task_python_code_tool_config_list",
            queryset=TaskPythonCodeToolConfigs.objects.select_related(
                "tool__tool__python_code"
            ),
        ),
        Prefetch(
            "task_context_list",
            queryset=TaskContext.objects.select_related("context"),
        ),
        Prefetch(
            "task_configured_tool_list",
            queryset=TaskConfiguredTools.objects.select_related(
                "tool__tool"
            ).prefetch_related("tool__tool__tool_fields"),
        ),
        Prefetch(
            "task_mcp_tool_list",
            queryset=TaskMcpTools.objects.select_related("tool"),
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


class ContentHashPreconditionMixin:
    """Passes content_hash from request data to the model instance before saving.

    The model's ContentHashMixin.save() validates _expected_hash against the DB,
    raising 409 Conflict on mismatch. Omitting content_hash skips the check.
    Scripts can also set instance._expected_hash = hash before calling .save().
    """

    def perform_update(self, serializer):
        incoming_hash = self.request.data.get("content_hash")
        if incoming_hash is not None:
            serializer.instance._expected_hash = incoming_hash
        super().perform_update(serializer)


class PythonCodeViewSet(ContentHashPreconditionMixin, viewsets.ModelViewSet):
    """
    A viewset for viewing and editing PythonCode instances.
    """

    queryset = PythonCode.objects.all()
    serializer_class = PythonCodeSerializer


class PythonCodeToolViewSet(CopyActionMixin, viewsets.ModelViewSet):
    """
    A viewset for viewing and editing PythonCodeTool instances.
    Prevents modifications or deletions of built-in tools.
    """

    copy_service_class = PythonCodeToolCopyService
    copy_serializer_class = PythonCodeToolSerializer

    queryset = (
        PythonCodeTool.objects.all()
        .select_related("python_code")
        .prefetch_related("tool_fields")
    )
    serializer_class = PythonCodeToolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "python_code"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.built_in:
            raise BuiltInToolModificationError()
        return super().destroy(request, *args, **kwargs)


class PythonCodeToolConfigViewSet(viewsets.ModelViewSet):
    queryset = PythonCodeToolConfig.objects.select_related("tool").prefetch_related(
        Prefetch(
            "tool__tool_fields",
            queryset=PythonCodeToolConfigField.objects.all(),
            to_attr="prefetched_config_fields",
        )
    )
    serializer_class = PythonCodeToolConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["tool", "name"]


class PythonCodeToolConfigFieldViewSet(viewsets.ModelViewSet):
    """
    A viewset for viewing and editing PythonCodeToolConfigFields instances.
    """

    queryset = PythonCodeToolConfigField.objects.all()
    serializer_class = PythonCodeToolConfigFieldSerializer
    filter_backends = [DjangoFilterBackend]


class PythonCodeResultReadViewSet(ReadOnlyModelViewSet):
    queryset = PythonCodeResult.objects.all()
    serializer_class = PythonCodeResultSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["execution_id", "returncode"]


class GraphViewSet(CopyActionMixin, viewsets.ModelViewSet):
    copy_service_class = GraphCopyService
    copy_serializer_class = GraphLightSerializer

    serializer_class = GraphSerializer
    filter_backends = [DjangoFilterBackend, LabelFilterBackend]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.GRAPH, export_prefix="graph", filename_attr="name"
        )

    def get_queryset(self):
        qs = (
            Graph.objects.defer("metadata", "tags")
            .prefetch_related(
                Prefetch(
                    "crew_node_list",
                    queryset=CrewNode.objects.select_related("crew").prefetch_related(
                        "crew__task_set"
                    ),
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
                Prefetch(
                    "subgraph_node_list",
                    queryset=SubGraphNode.objects.select_related(
                        "subgraph"
                    ).prefetch_related("subgraph__tags"),
                ),
                Prefetch(
                    "code_agent_node_list",
                    queryset=CodeAgentNode.objects.select_related("llm_config"),
                ),
                Prefetch("end_node", queryset=EndNode.objects.all()),
                Prefetch(
                    "telegram_trigger_node_list",
                    queryset=TelegramTriggerNode.objects.all(),
                ),
                "start_node_list",
                Prefetch("graph_note_list", queryset=GraphNote.objects.all()),
            )
            .all()
        )
        return qs

    def perform_create(self, serializer):
        created_graph = serializer.save()
        organization, _ = Organization.objects.get_or_create(
            name=DEFAULT_ORGANIZATION_NAME
        )
        GraphOrganization.objects.create(graph=created_graph, organization=organization)

    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(self.get_object())

    @action(detail=False, methods=["post"], url_path="bulk-export")
    def bulk_export(self, request):
        serializer = BulkExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity_ids = serializer.validated_data["ids"]

        existing_ids = Graph.objects.filter(id__in=entity_ids).values_list(
            "id", flat=True
        )
        if len(existing_ids) != len(entity_ids):
            return Response(
                {"message": "Some entity IDs do not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return self.import_export_service.bulk_export(entity_ids)

    @action(detail=False, methods=["post"], url_path="import")
    def import_entity(self, request):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)

        data = self.import_export_service.import_entity(
            file_serializer.validated_data["file"],
            preserve_uuids=file_serializer.validated_data["preserve_uuids"],
        )
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="save")
    @swagger_auto_schema(**_SAVE_FLOW_SWAGGER)
    def save_flow(self, request, pk=None):
        input_serializer = GraphBulkSaveInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(
                {"errors": input_serializer.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        graph = self.get_object()
        try:
            GraphBulkSaveService().save(graph, input_serializer.validated_data)
        except BulkSaveValidationError as exc:
            return Response({"errors": exc.errors}, status=status.HTTP_400_BAD_REQUEST)

        refreshed = self.get_queryset().get(pk=pk)
        return Response(GraphSerializer(refreshed).data, status=status.HTTP_200_OK)


class GraphLightViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GraphLightSerializer
    filter_backends = [
        DjangoFilterBackend,
        drf_filters.SearchFilter,
        LabelFilterBackend,
    ]
    filterset_fields = ["epicchat_enabled"]
    search_fields = ["name", "description"]

    def get_queryset(self):
        return Graph.objects.only("id", "name", "description").prefetch_related(
            "tags", "labels"
        )


class IdempotentNodeCreateMixin:
    # TODO: change fields from (graph, node_name) to id (all nodes id's are consistent)
    """
    COMMIT_COMMENTS: Makes node POST idempotent — if a node with the same
    (graph, node_name) already exists, update it instead of failing with a
    unique constraint violation. This prevents orphan accumulation when
    forkJoin-based saves partially fail and retry.
    """

    def create(self, request, *args, **kwargs):
        graph_id = request.data.get("graph")
        node_name = request.data.get("node_name")
        if graph_id and node_name:
            try:
                existing = self.get_queryset().model.objects.get(
                    graph_id=graph_id, node_name=node_name
                )
                serializer = self.get_serializer(existing, data=request.data)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            except self.get_queryset().model.DoesNotExist:
                pass
        return super().create(request, *args, **kwargs)


class CrewNodeViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    queryset = CrewNode.objects.all()
    serializer_class = CrewNodeSerializer


class PythonNodeViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    queryset = PythonNode.objects.all()
    serializer_class = PythonNodeSerializer


class FileExtractorNodeViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    queryset = FileExtractorNode.objects.all()
    serializer_class = FileExtractorNodeSerializer


class AudioTranscriptionNodeViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    queryset = AudioTranscriptionNode.objects.all()
    serializer_class = AudioTranscriptionNodeSerializer


class LLMNodeViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    queryset = LLMNode.objects.all()
    serializer_class = LLMNodeSerializer


class CodeAgentNodeViewSet(IdempotentNodeCreateMixin, viewsets.ModelViewSet):
    queryset = CodeAgentNode.objects.all()
    serializer_class = CodeAgentNodeSerializer


class EdgeViewSet(ContentHashPreconditionMixin, viewsets.ModelViewSet):
    queryset = Edge.objects.all()
    serializer_class = EdgeSerializer


class ConditionalEdgeViewSet(ContentHashPreconditionMixin, viewsets.ModelViewSet):
    queryset = ConditionalEdge.objects.all()
    serializer_class = ConditionalEdgeSerializer


class GraphSessionMessageReadOnlyViewSet(ReadOnlyModelViewSet):
    queryset = GraphSessionMessage.objects.all()
    serializer_class = GraphSessionMessageSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["session_id"]


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


class StartNodeModelViewSet(ContentHashPreconditionMixin, viewsets.ModelViewSet):
    queryset = StartNode.objects.all()
    serializer_class = StartNodeSerializer


class EndNodeModelViewSet(ContentHashPreconditionMixin, viewsets.ModelViewSet):
    queryset = EndNode.objects.all()
    serializer_class = EndNodeSerializer


class SubGraphNodeModelViewSet(ContentHashPreconditionMixin, viewsets.ModelViewSet):
    queryset = SubGraphNode.objects.all()
    serializer_class = SubGraphNodeSerializer


class ConditionGroupModelViewSet(viewsets.ModelViewSet):
    queryset = ConditionGroup.objects.all()
    serializer_class = ConditionGroupSerializer


class ConditionModelViewSet(viewsets.ModelViewSet):
    queryset = Condition.objects.all()
    serializer_class = ConditionSerializer


class DecisionTableNodeModelViewSet(
    ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    queryset = DecisionTableNode.objects.all()
    serializer_class = DecisionTableNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph"]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Create a DecisionTableNode along with nested ConditionGroups and Conditions.
        If a node with the same (graph, node_name) already exists, update it instead.
        """
        graph_id = request.data.get("graph")
        node_name = request.data.get("node_name")
        if graph_id and node_name:
            try:
                existing = DecisionTableNode.objects.get(
                    graph_id=graph_id, node_name=node_name
                )
                node, _ = self._create_or_update_node(
                    data=request.data, instance=existing
                )
                return Response(
                    self.get_serializer(node).data, status=status.HTTP_200_OK
                )
            except DecisionTableNode.DoesNotExist:
                pass
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
        incoming_hash = request.data.get("content_hash")
        if incoming_hash is not None:
            instance._expected_hash = incoming_hash
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
        for group_data in groups_data:
            copy_group_data = group_data.copy()
            conditions_data = copy_group_data.pop("conditions", [])
            copy_group_data.pop("decision_table_node", None)
            copy_group_data.pop("content_hash", None)

            group = ConditionGroup.objects.create(
                decision_table_node=node, **copy_group_data
            )

            for cond_data in conditions_data:
                cond_data = {
                    k: v
                    for k, v in cond_data.items()
                    if k not in ("condition_group", "content_hash")
                }
                Condition.objects.create(condition_group=group, **cond_data)

            # Re-save group so its hash includes the newly created conditions
            group.save()

        # Re-save node so its hash includes the updated group hashes
        node.save()


class ClassificationDecisionTableNodeModelViewSet(viewsets.ModelViewSet):
    queryset = ClassificationDecisionTableNode.objects.all()
    serializer_class = ClassificationDecisionTableNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph"]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        node, _ = self._create_or_update_node(data=request.data)
        return Response(self.get_serializer(node).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        node, _ = self._create_or_update_node(
            data=request.data, instance=instance, partial=partial
        )
        return Response(self.get_serializer(node).data, status=status.HTTP_200_OK)

    def _create_or_update_node(self, data, instance=None, partial=False):
        data = data.copy()
        condition_groups_data = data.pop("condition_groups", None)
        prompt_configs_data = data.pop("prompt_configs", None)

        node_serializer = self.get_serializer(instance, data=data, partial=partial)
        node_serializer.is_valid(raise_exception=True)
        node = node_serializer.save()

        if partial and condition_groups_data is None and prompt_configs_data is None:
            return node, None

        if instance:
            ClassificationConditionGroup.objects.filter(
                classification_decision_table_node=node
            ).delete()

        if condition_groups_data:
            groups_to_create = []
            for group_data in condition_groups_data:
                gd = {
                    k: v
                    for k, v in group_data.items()
                    if k not in ("id", "classification_decision_table_node")
                }
                groups_to_create.append(
                    ClassificationConditionGroup(
                        classification_decision_table_node=node, **gd
                    )
                )
            ClassificationConditionGroup.objects.bulk_create(groups_to_create)

        if prompt_configs_data is not None:
            if instance:
                ClassificationDecisionTablePrompt.objects.filter(cdt_node=node).delete()

            ClassificationDecisionTablePrompt.objects.bulk_create(
                [
                    ClassificationDecisionTablePrompt(
                        cdt_node=node,
                        llm_config_id=prompt_data.get("llm_config"),
                        **{
                            k: v
                            for k, v in prompt_data.items()
                            if k not in ("id", "cdt_node", "llm_config")
                        },
                    )
                    for prompt_data in prompt_configs_data
                ]
            )

        return node, condition_groups_data


class McpToolViewSet(CopyActionMixin, viewsets.ModelViewSet):
    copy_service_class = McpToolCopyService
    copy_serializer_class = McpToolSerializer

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


class WebhookTriggerNodeViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    queryset = WebhookTriggerNode.objects.all()
    serializer_class = WebhookTriggerNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph", "node_name", "webhook_trigger__path"]

    def create(self, request, *args, **kwargs):
        logger.info(f"[WebhookTriggerNode] CREATE payload: {request.data}")
        try:
            return super().create(request, *args, **kwargs)
        except DRFValidationError as e:
            logger.error(f"[WebhookTriggerNode] validation error: {e.detail}")
            raise
        except Exception as e:
            logger.error(f"[WebhookTriggerNode] unexpected error: {e}")
            raise


class WebhookTriggerViewSet(viewsets.ModelViewSet):
    queryset = WebhookTrigger.objects.all()
    serializer_class = WebhookTriggerSerializer
    filter_backends = [DjangoFilterBackend]


class TelegramTriggerNodeViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, ModelViewSet
):
    queryset = TelegramTriggerNode.objects.prefetch_related("fields")
    serializer_class = TelegramTriggerNodeSerializer


class TelegramTriggerNodeFieldViewSet(ModelViewSet):
    queryset = TelegramTriggerNodeField.objects.select_related("telegram_trigger_node")
    serializer_class = TelegramTriggerNodeFieldSerializer


class GraphNoteViewSet(
    IdempotentNodeCreateMixin, ContentHashPreconditionMixin, ModelViewSet
):
    queryset = GraphNote.objects.all()
    serializer_class = GraphNoteSerializer


class NgrokWebhookConfigViewSet(ModelViewSet):
    queryset = NgrokWebhookConfig.objects.all()
    serializer_class = NgrokWebhookConfigModelSerializer

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        instance = NgrokWebhookConfig.objects.get(pk=response.data["id"])
        WebhookTriggerService().wait_for_tunnel_url(instance)
        response.data = self.get_serializer(instance).data
        return response

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        instance = NgrokWebhookConfig.objects.get(pk=response.data["id"])
        WebhookTriggerService().wait_for_tunnel_url(instance)
        response.data = self.get_serializer(instance).data
        return response


class LabelViewSet(viewsets.ModelViewSet):
    queryset = Label.objects.all()
    serializer_class = LabelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "parent"]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        labels = list(queryset)

        # Build paths in memory (one extra lightweight query) to avoid N+1
        # and to correctly resolve parents that may be filtered out.
        id_to_row = {
            row["id"]: row for row in Label.objects.values("id", "parent_id", "name")
        }

        def full_path_key(label):
            parts = []
            current_id = label.id
            while current_id is not None:
                row = id_to_row.get(current_id)
                if row is None:
                    break
                parts.append(row["name"])
                current_id = row["parent_id"]
            return "/".join(reversed(parts))

        labels.sort(key=lambda label: natural_sort_key(full_path_key(label)))

        page = self.paginate_queryset(labels)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        return Response(self.get_serializer(labels, many=True).data)


class VoiceSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = VoiceSettingsSerializer

    def get_object(self):
        return VoiceSettings.load()

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        redis_service.redis_client.publish("voice_settings:invalidate", "{}")
        return response


def _twilio_request(
    account_sid: str, auth_token: str, url: str, method: str = "GET", data: dict = None
):
    """Make an authenticated request to the Twilio REST API."""
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}
    body = None
    if data:
        encoded = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = encoded
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


class TwilioPhoneNumbersView(generics.GenericAPIView):
    """Return the list of incoming phone numbers from Twilio."""

    def get(self, request):
        vs = VoiceSettings.load()
        if not vs.twilio_account_sid or not vs.twilio_auth_token:
            return Response(
                {"error": "Twilio Account SID and Auth Token are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{vs.twilio_account_sid}/IncomingPhoneNumbers.json?PageSize=100"
            data = _twilio_request(vs.twilio_account_sid, vs.twilio_auth_token, url)
            numbers = [
                {
                    "sid": n["sid"],
                    "phone_number": n["phone_number"],
                    "friendly_name": n["friendly_name"],
                    "voice_url": n.get("voice_url") or "",
                }
                for n in data.get("incoming_phone_numbers", [])
            ]
            return Response(numbers)
        except urllib.error.HTTPError as e:
            return Response({"error": e.read().decode()}, status=e.code)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


class TwilioConfigureWebhookView(generics.GenericAPIView):
    """Set the VoiceUrl on a Twilio phone number to the configured voice stream URL."""

    def post(self, request):
        phone_sid = request.data.get("phone_sid")
        if not phone_sid:
            return Response(
                {"error": "phone_sid is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        vs = VoiceSettings.load()
        if not vs.twilio_account_sid or not vs.twilio_auth_token:
            return Response(
                {"error": "Twilio Account SID and Auth Token are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from tables.serializers.model_serializers import VoiceSettingsSerializer

        voice_stream_url = VoiceSettingsSerializer(vs).data.get("voice_stream_url")
        if not voice_stream_url:
            return Response(
                {
                    "error": "No voice stream URL configured — set up an ngrok tunnel first"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Twilio expects the webhook as an HTTP/HTTPS URL not WSS
        # voice_stream_url is wss://host/voice/stream → https://host/voice
        webhook_url = (
            voice_stream_url.replace("wss://", "https://")
            .replace("/stream", "")
            .rstrip("/")
        )

        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{vs.twilio_account_sid}/IncomingPhoneNumbers/{phone_sid}.json"
            _twilio_request(
                vs.twilio_account_sid,
                vs.twilio_auth_token,
                url,
                method="POST",
                data={"VoiceUrl": webhook_url, "VoiceMethod": "POST"},
            )
            return Response({"webhook_url": webhook_url})
        except urllib.error.HTTPError as e:
            return Response({"error": e.read().decode()}, status=e.code)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
