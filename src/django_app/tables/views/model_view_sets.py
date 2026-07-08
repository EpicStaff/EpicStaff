import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.db.models import NOT_PROVIDED, IntegerField, Prefetch, Q
from django.db.models.functions import Cast
from django_filters import rest_framework as filters
from django_filters.rest_framework import (
    CharFilter,
    DjangoFilterBackend,
    FilterSet,
    NumberFilter,
)
from rest_framework import filters as drf_filters
from rest_framework import generics, mixins, status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from tables.serializers.model_serializers.embedding_serializers import (
    EmbeddingConfigSerializer,
    EmbeddingModelSerializer,
)
from tables.serializers.model_serializers.llm_serializers import (
    LLMConfigSerializer,
    LLMModelSerializer,
    RealtimeConfigSerializer,
    RealtimeModelSerializer,
    RealtimeTranscriptionConfigSerializer,
    RealtimeTranscriptionModelSerializer,
)
from tables.serializers.model_serializers.provider_serializers import (
    ProviderSerializer,
)
from tables.serializers.model_serializers.tag_serializers import (
    AgentTagSerializer,
    CrewTagSerializer,
    GraphTagSerializer,
)
from tables.exceptions import (
    AgentSerializerError,
    BuiltInToolModificationError,
    BulkSaveValidationError,
    TaskSerializerError,
    GraphSaveVersionConflictError,
)
from tables.serializers.graph_bulk_save_serializers import GraphBulkSaveInputSerializer
from tables.services.graph_bulk_save_service import GraphBulkSaveService
from tables.graph_versioning.services import GraphVersioningService
from tables.graph_versioning.serializers import (
    GraphVersionCreateSerializer,
    GraphVersionReadSerializer,
    GraphVersionUpdateSerializer,
    RestoreVersionInputSerializer,
)

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
    GraphVersion,
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
    TaskConfiguredTools,
    TaskMcpTools,
    TaskPythonCodeToolConfigs,
    TaskPythonCodeTools,
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
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    inline_serializer,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes
from tables.swagger_schemas.knowledge_schemas.graph_bulk_save_schemas import (
    SAVE_FLOW_SWAGGER as _SAVE_FLOW_SWAGGER,
)
from tables.swagger_schemas.partial_import_schemas import (
    PARTIAL_IMPORT_SWAGGER as PARTIAL_IMPORT_SWAGGER,
)
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.exceptions import PermissionDenied, NotFound
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
    ClassificationDecisionTableNode,
    Condition,
    ConditionGroup,
    DecisionTableNode,
    EndNode,
    GraphOrganization,
    GraphOrganizationUser,
    GraphNote,
    TelegramTriggerNode,
    WebhookTriggerNode,
    ScheduleTriggerNode,
)
from tables.models.llm_models import (
    RealtimeConfig,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
)
from tables.models.knowledge_models.naive_rag_models import AgentNaiveRag
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeToolConfig
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
from tables.views.mixins import (
    CopyActionMixin,
    OrgScopedChildViewSetMixin,
    OrgScopedHybridViewSetMixin,
    OrgScopedQuerysetMixin,
    OrgScopedViewSetMixin,
    SuperadminWriteMixin,
)
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.permissions import HasOrgPermission, IsSuperadmin
from tables.services.rbac.permission_action_map import DEFAULT_ACTION_MAP
from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
    validate_classification_condition_group_names,
)
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
    DecisionTableNodeSerializer,
    EdgeSerializer,
    EndNodeSerializer,
    FileExtractorNodeSerializer,
    GraphLightSerializer,
    GraphOrganizationSerializer,
    GraphOrganizationUserSerializer,
    GraphSerializer,
    GraphSessionMessageSerializer,
    LabelSerializer,
    McpToolSerializer,
    MemorySerializer,
    NgrokWebhookConfigModelSerializer,
    ProviderSerializer,
    PythonCodeResultSerializer,
    PythonCodeSerializer,
    PythonCodeToolConfigSerializer,
    PythonCodeToolSerializer,
    PythonNodeSerializer,
    RealtimeAgentChatSerializer,
    RealtimeAgentSerializer,
    RealtimeSessionItemSerializer,
    StartNodeSerializer,
    SubGraphNodeSerializer,
    TaskReadSerializer,
    TaskWriteSerializer,
    TemplateAgentSerializer,
    ToolConfigSerializer,
    VoiceSettingsSerializer,
    WebhookTriggerNodeSerializer,
    WebhookTriggerSerializer,
    ScheduleTriggerNodeSerializer,
    TelegramTriggerNodeSerializer,
)

from tables.serializers.serializers import (
    BulkExportSerializer,
    GraphNodesPartialExportSerializer,
    ImportRequestSerializer,
)
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
    LIST_KEY_TO_ENTITY_TYPE,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.utils.helpers import generate_file_name
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.services.import_export_service import ViewSetImportExportService
from tables.services.classification_decision_table_node_service import (
    ClassificationDecisionTableNodeService,
)
from tables.import_export.services.import_service import ImportSettings
from tables.services.redis_service import RedisService
from tables.swagger_schemas.twilio_schemas import (
    TWILIO_PHONE_NUMBERS_GET,
    TWILIO_CONFIGURE_WEBHOOK_POST,
)
from tables.graph_collab.notifications import GraphEditNotifier
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


class LLMConfigReadWriteViewSet(OrgScopedViewSetMixin, ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}

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


class ProviderReadWriteViewSet(SuperadminWriteMixin, ModelViewSet):
    queryset = Provider.objects.all()
    serializer_class = ProviderSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProviderFilter


class LLMModelReadWriteViewSet(
    OrgScopedHybridViewSetMixin, BasePredefinedRestrictedViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    global_visibility_q = Q(is_custom=False)
    # force created rows into the org's custom, non-predefined subset (also
    # preserves BasePredefinedRestrictedViewSet's "no creating predefined" rule)
    custom_create_values = {"is_custom": True, "predefined": False}
    queryset = LLMModel.objects.select_related("llm_provider").prefetch_related("tags")
    serializer_class = LLMModelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = LLMModelFilter


class EmbeddingModelReadWriteViewSet(
    OrgScopedHybridViewSetMixin, BasePredefinedRestrictedViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    global_visibility_q = Q(is_custom=False)
    # force created rows into the org's custom, non-predefined subset (also
    # preserves BasePredefinedRestrictedViewSet's "no creating predefined" rule)
    custom_create_values = {"is_custom": True, "predefined": False}
    queryset = EmbeddingModel.objects.select_related(
        "embedding_provider"
    ).prefetch_related("tags")
    serializer_class = EmbeddingModelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = EmbeddingModelFilter


class EmbeddingConfigReadWriteViewSet(OrgScopedViewSetMixin, ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}

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


class AgentViewSet(OrgScopedViewSetMixin, CopyActionMixin, ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
    }
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

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                },
                "required": ["file"],
            }
        }
    )
    @action(detail=False, methods=["post"], url_path="import")
    def import_entity(self, request):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)

        data = self.import_export_service.import_entity(
            file_serializer.validated_data["file"],
            user=request.user,
            org_id=self.get_active_org_id(),
        )
        return Response(data, status=status.HTTP_200_OK)


class CrewReadWriteViewSet(OrgScopedViewSetMixin, CopyActionMixin, ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.PROJECTS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
    }
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
            file_serializer.validated_data["file"],
            user=request.user,
            org_id=self.get_active_org_id(),
        )
        return Response(data, status=status.HTTP_200_OK)


class TaskReadWriteViewSet(OrgScopedChildViewSetMixin, ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.PROJECTS
    org_filter_path = "crew__org_id"
    queryset = Task.objects.prefetch_related(
        Prefetch(
            "task_python_code_tool_list",
            queryset=TaskPythonCodeTools.objects.select_related("tool__python_code"),
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
            queryset=TaskConfiguredTools.objects.select_related("tool__tool"),
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
    # """Passes content_hash from request data to the model instance before saving.

    # The model's ContentHashMixin.save() validates _expected_hash against the DB,
    # raising 409 Conflict on mismatch. Omitting content_hash skips the check.
    # Scripts can also set instance._expected_hash = hash before calling .save().
    # """

    def perform_update(self, serializer):
        incoming_hash = self.request.data.get("content_hash")
        if incoming_hash is not None:
            serializer.instance._expected_hash = incoming_hash
        super().perform_update(serializer)


class PythonCodeViewSet(
    OrgScopedQuerysetMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    """
    A viewset for viewing and editing PythonCode instances.

    PythonCode has no org column of its own; it is scoped transitively through
    every parent that references it — python/conditional/webhook-trigger nodes
    (via their graph's org) and python-code tools (built-in are global, custom
    are org-owned). A standalone PythonCode not yet attached to any parent is
    not visible here until it is linked.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    scope_distinct = True  # the OR spans reverse joins that can duplicate rows
    queryset = PythonCode.objects.all()
    serializer_class = PythonCodeSerializer

    def get_org_scope_q(self, org_id: int) -> Q:
        return (
            Q(pythonnode__graph__org_id=org_id)
            | Q(conditionaledge__graph__org_id=org_id)
            | Q(webhooktriggernode__graph__org_id=org_id)
            | Q(pythoncodetool__built_in=True)
            | Q(pythoncodetool__org_id=org_id)
        )


class PythonCodeToolViewSet(
    OrgScopedHybridViewSetMixin, CopyActionMixin, viewsets.ModelViewSet
):
    """
    A viewset for viewing and editing PythonCodeTool instances.
    Built-in tools are global; custom tools are org-owned.
    Prevents modifications or deletions of built-in tools.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    global_visibility_q = Q(built_in=True)
    custom_create_values = {"built_in": False}

    copy_service_class = PythonCodeToolCopyService
    copy_serializer_class = PythonCodeToolSerializer

    queryset = PythonCodeTool.objects.all().select_related("python_code")
    serializer_class = PythonCodeToolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "python_code"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.built_in:
            raise BuiltInToolModificationError()
        return super().destroy(request, *args, **kwargs)


class PythonCodeToolConfigViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    queryset = PythonCodeToolConfig.objects.select_related("tool")
    serializer_class = PythonCodeToolConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["tool", "name"]


class PythonCodeResultReadViewSet(ReadOnlyModelViewSet):
    # TODO(EST-2423): org-scope python execution results.
    queryset = PythonCodeResult.objects.all()
    serializer_class = PythonCodeResultSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["execution_id", "returncode"]


class GraphViewSet(OrgScopedViewSetMixin, CopyActionMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "export": Permission.EXPORT,
        "bulk_export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
        "save_flow": Permission.UPDATE,
    }
    copy_service_class = GraphCopyService
    copy_serializer_class = GraphLightSerializer

    serializer_class = GraphSerializer
    filter_backends = [DjangoFilterBackend, LabelFilterBackend]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.GRAPH, export_prefix="graph", filename_attr="name"
        )
        self._partial_export_service = GraphPartialExportService(entity_registry)

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
                Prefetch(
                    "schedule_trigger_node_list",
                    queryset=ScheduleTriggerNode.objects.all(),
                ),
                "start_node_list",
                Prefetch("graph_note_list", queryset=GraphNote.objects.all()),
            )
            .all()
        )
        return qs.filter(org_id=self.get_active_org_id())

    def perform_create(self, serializer):
        org_id = self.get_active_org_id()
        created_graph = serializer.save(org_id=org_id, created_by=self.request.user)
        GraphOrganization.objects.create(graph=created_graph)

    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(self.get_object())

    @action(detail=False, methods=["post"], url_path="bulk-export")
    def bulk_export(self, request):
        serializer = BulkExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity_ids = serializer.validated_data["ids"]

        existing_ids = Graph.objects.filter(
            id__in=entity_ids, org_id=self.get_active_org_id()
        ).values_list("id", flat=True)
        if len(existing_ids) != len(entity_ids):
            return Response(
                {"message": "Some entity IDs do not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return self.import_export_service.bulk_export(entity_ids)

    @extend_schema(request=GraphNodesPartialExportSerializer, responses={200: None})
    @action(detail=True, methods=["post"], url_path="partial-export")
    def partial_export(self, request, pk=None):
        serializer = GraphNodesPartialExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        graph = self.get_object()
        node_refs = [
            NodeRef(entity_type=entity_type, node_id=node_id)
            for list_key, entity_type in LIST_KEY_TO_ENTITY_TYPE.items()
            for node_id in serializer.validated_data.get(list_key, [])
        ]

        result = self._partial_export_service.export(
            node_refs,
            edge_ids=serializer.validated_data.get("edge_list", []),
        )

        if result.has_errors:
            return Response(
                {"errors": result.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        filename = generate_file_name(f"nodes_{graph.name}", prefix="graph_nodes")
        response = HttpResponse(
            json.dumps(result.data, indent=4), content_type="application/json"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=["post"], url_path="import")
    def import_entity(self, request):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)

        vd = file_serializer.validated_data
        data = self.import_export_service.import_entity(
            vd["file"],
            user=request.user,
            settings=ImportSettings(
                preserve_uuids=vd["preserve_uuids"],
                replace_existing=vd["replace_existing"],
                import_labels=vd["import_labels"],
            ),
            org_id=self.get_active_org_id(),
        )
        return Response(data, status=status.HTTP_200_OK)

    @extend_schema(**PARTIAL_IMPORT_SWAGGER)
    @action(detail=True, methods=["post"], url_path="partial-import")
    def partial_import(self, request, pk=None):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)

        try:
            data = json.load(file_serializer.validated_data["file"])
        except (json.JSONDecodeError, UnicodeDecodeError, Exception):
            raise DRFValidationError(
                {"detail": "File format is incorrect. Please upload a valid JSON file."}
            )

        graph = self.get_object()
        partial_import_service = PartialImportService(entity_registry)
        id_mapper = partial_import_service.import_data(data, graph)
        summary = id_mapper.get_detailed_summary(entity_registry)
        return Response(summary, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        instance = self.get_object()
        instance.refresh_from_db(fields=["save_version"])

        GraphEditNotifier.notify_graph_saved(
            graph_id=instance.pk,
            new_save_version=instance.save_version,
            user=request.user,
            saved_at=timezone.now().isoformat(),
        )
        return response

    @action(detail=True, methods=["post"], url_path="save")
    @extend_schema(**_SAVE_FLOW_SWAGGER)
    def save_flow(self, request, pk=None):
        input_serializer = GraphBulkSaveInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(
                {"errors": input_serializer.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        graph = self.get_object()
        try:
            GraphBulkSaveService().save(
                graph, input_serializer.validated_data, request=request
            )
        except BulkSaveValidationError as exc:
            return Response({"errors": exc.errors}, status=status.HTTP_400_BAD_REQUEST)
        # GraphSaveVersionConflictError propagates → DRF returns 409 automatically.

        refreshed = self.get_queryset().get(pk=pk)

        GraphEditNotifier.notify_graph_saved(
            graph_id=refreshed.pk,
            new_save_version=refreshed.save_version,
            user=request.user,
            saved_at=timezone.now().isoformat(),
        )

        return Response(GraphSerializer(refreshed).data, status=status.HTTP_200_OK)


class GraphLightViewSet(OrgScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    serializer_class = GraphLightSerializer
    filter_backends = [
        DjangoFilterBackend,
        drf_filters.SearchFilter,
        LabelFilterBackend,
    ]
    filterset_fields = ["epicchat_enabled"]
    search_fields = ["name", "description"]

    def get_queryset(self):
        return (
            Graph.objects.only("id", "name", "description")
            .prefetch_related("tags", "labels")
            .filter(org_id=self.get_active_org_id())
        )


@extend_schema_view(
    restore=extend_schema(
        request=RestoreVersionInputSerializer,
        responses={
            200: inline_serializer(
                name="RestoreResponse",
                fields={
                    "graph_id": serializers.IntegerField(),
                    "warnings": serializers.ListField(child=serializers.DictField()),
                    "auto_backup_version_id": serializers.IntegerField(allow_null=True),
                },
            )
        },
        parameters=[
            OpenApiParameter(
                name="backup",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="If true, creates a backup version before restoring.",
            )
        ],
    ),
    create_graph=extend_schema(
        request=None,
        responses={
            201: inline_serializer(
                name="CreateFromVersionResponse",
                fields={
                    "graph_id": serializers.IntegerField(),
                    "warnings": serializers.ListField(child=serializers.DictField()),
                },
            )
        },
    ),
)
class GraphVersionViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "all": Permission.READ,
        "restore": Permission.UPDATE,
        "create_graph": Permission.CREATE,
    }
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph_id"]

    def get_queryset(self):
        manager = (
            GraphVersion.all_objects if self.action == "all" else GraphVersion.objects
        )
        qs = manager.all()
        if self.action in ("list", "all"):
            qs = qs.defer("snapshot", "dependencies")
        return qs.filter(graph__org_id=self.get_active_org_id())

    def get_serializer_class(self):
        if self.action == "create":
            return GraphVersionCreateSerializer
        if self.action in ("update", "partial_update"):
            return GraphVersionUpdateSerializer
        return GraphVersionReadSerializer

    def create(self, request, *args, **kwargs):
        serializer_class = self.get_serializer_class()
        write_serializer = serializer_class(data=request.data)
        write_serializer.is_valid(raise_exception=True)

        graph = write_serializer.validated_data["graph"]
        # Cannot version a flow outside the active org.
        if graph.org_id != self.get_active_org_id():
            raise NotFound()

        version = GraphVersioningService().save_version(
            graph=graph,
            name=write_serializer.validated_data["name"],
            description=write_serializer.validated_data.get("description", ""),
        )

        return Response(
            GraphVersionReadSerializer(version).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="all")
    def all(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, *args, **kwargs):
        input_serializer = RestoreVersionInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        expected_save_version = input_serializer.validated_data["save_version"]

        version = self.get_object()
        backup = request.query_params.get("backup", "").lower() == "true"
        result = GraphVersioningService().restore_version(
            version,
            expected_save_version=expected_save_version,
            backup=backup,
        )

        graph_id = result["graph_id"]
        new_save_version = Graph.objects.values("save_version").get(pk=graph_id)[
            "save_version"
        ]

        GraphEditNotifier.notify_graph_saved(
            graph_id=graph_id,
            new_save_version=new_save_version,
            user=request.user,
            saved_at=timezone.now().isoformat(),
        )

        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="create-graph")
    def create_graph(self, request, *args, **kwargs):
        version = self.get_object()
        result = GraphVersioningService().create_graph_from_version(version)
        return Response(result, status=status.HTTP_201_CREATED)


class IdempotentNodeCreateMixin:
    # TODO: change fields from (graph, node_name) to id (all nodes id's are consistent)
    # """
    # COMMIT_COMMENTS: Makes node POST idempotent — if a node with the same
    # (graph, node_name) already exists, update it instead of failing with a
    # unique constraint violation. This prevents orphan accumulation when
    # forkJoin-based saves partially fail and retry.
    # """

    def create(self, request, *args, **kwargs):
        graph_id = request.data.get("graph")
        node_name = request.data.get("node_name")
        if graph_id and node_name:
            # Org-scoped queryset: an idempotent match only updates a node whose
            # graph is in the active org; a node in another org is never touched.
            queryset = self.get_queryset()
            try:
                existing = queryset.get(graph_id=graph_id, node_name=node_name)
                serializer = self.get_serializer(existing, data=request.data)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            except queryset.model.DoesNotExist:
                pass
        return super().create(request, *args, **kwargs)


class CrewNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = CrewNode.objects.all()
    serializer_class = CrewNodeSerializer


class PythonNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = PythonNode.objects.all()
    serializer_class = PythonNodeSerializer


class FileExtractorNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = FileExtractorNode.objects.all()
    serializer_class = FileExtractorNodeSerializer


class AudioTranscriptionNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = AudioTranscriptionNode.objects.all()
    serializer_class = AudioTranscriptionNodeSerializer


class CodeAgentNodeViewSet(
    OrgScopedChildViewSetMixin, IdempotentNodeCreateMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = CodeAgentNode.objects.all()
    serializer_class = CodeAgentNodeSerializer


class EdgeViewSet(
    OrgScopedChildViewSetMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = Edge.objects.all()
    serializer_class = EdgeSerializer


class ConditionalEdgeViewSet(
    OrgScopedChildViewSetMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = ConditionalEdge.objects.all()
    serializer_class = ConditionalEdgeSerializer


class GraphSessionMessageFilter(FilterSet):
    session_id = NumberFilter(field_name="session_id", lookup_expr="exact")
    parent_subgraph_execution_id = filters.UUIDFilter(
        field_name="parent_subgraph_execution_id", lookup_expr="exact"
    )

    class Meta:
        model = GraphSessionMessage
        fields = ["session_id", "parent_subgraph_execution_id"]


class GraphSessionMessageReadOnlyViewSet(
    OrgScopedChildViewSetMixin, ReadOnlyModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "session__graph__org_id"
    queryset = GraphSessionMessage.objects.all().order_by("id")
    serializer_class = GraphSessionMessageSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = GraphSessionMessageFilter

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.query_params.get("parent_subgraph_execution_id"):
            qs = qs.filter(parent_subgraph_execution_id__isnull=True)
        return qs


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
    # TODO(EST-2423 deferred):  org-scope agent memory. MemoryDatabase has no org
    # link (UUID pk; agent_id/user_id live inside the opaque JSON payload), so it
    # needs a denormalized org before it can be scoped. Authenticated-only for now.
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


class RealtimeModelViewSet(OrgScopedHybridViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    global_visibility_q = Q(is_custom=False)
    custom_create_values = {"is_custom": True}
    queryset = RealtimeModel.objects.all()
    serializer_class = RealtimeModelSerializer


class RealtimeConfigModelViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}

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


class RealtimeTranscriptionModelViewSet(
    OrgScopedHybridViewSetMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    global_visibility_q = Q(is_custom=False)
    custom_create_values = {"is_custom": True}
    queryset = RealtimeTranscriptionModel.objects.all()
    serializer_class = RealtimeTranscriptionModelSerializer


class RealtimeTranscriptionConfigModelViewSet(
    OrgScopedViewSetMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}

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
    # TODO(EST-2423 deferred): org-scope realtime session items. Keyed by an
    # opaque connection_key with no org/agent FK; needs a denormalized org to
    # scope. Authenticated-only for now.
    queryset = RealtimeSessionItem.objects.all()
    serializer_class = RealtimeSessionItemSerializer


class RealtimeAgentViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    org_filter_path = "agent__org_id"
    queryset = RealtimeAgent.objects.all()
    serializer_class = RealtimeAgentSerializer


class RealtimeAgentChatViewSet(OrgScopedChildViewSetMixin, ReadOnlyModelViewSet):
    """
    ViewSet for reading and deleting RealtimeAgentChat instances.

    Scoped through the chat's realtime agent to its agent's org. Chats whose
    rt_agent is NULL (orphaned) are not visible — acceptable for chat history.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    org_filter_path = "rt_agent__agent__org_id"
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


class StartNodeModelViewSet(
    OrgScopedChildViewSetMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = StartNode.objects.all()
    serializer_class = StartNodeSerializer


class EndNodeModelViewSet(
    OrgScopedChildViewSetMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = EndNode.objects.all()
    serializer_class = EndNodeSerializer


class SubGraphNodeModelViewSet(
    OrgScopedChildViewSetMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = SubGraphNode.objects.all()
    serializer_class = SubGraphNodeSerializer


class ConditionGroupModelViewSet(viewsets.ModelViewSet):
    queryset = ConditionGroup.objects.all()
    serializer_class = ConditionGroupSerializer


class ConditionModelViewSet(viewsets.ModelViewSet):
    queryset = Condition.objects.all()
    serializer_class = ConditionSerializer


class DecisionTableNodeModelViewSet(
    OrgScopedChildViewSetMixin, ContentHashPreconditionMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._node_service = ClassificationDecisionTableNodeService()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        node, _ = self._node_service.create_or_update(data=request.data)
        return Response(self.get_serializer(node).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        node, _ = self._node_service.create_or_update(
            data=request.data, instance=instance, partial=partial
        )
        return Response(self.get_serializer(node).data, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="export_format",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["json", "csv"],
                description="Export format. Defaults to 'json'.",
            )
        ],
        responses={200: OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="export")
    def export(self, request, pk=None):
        export_format = request.query_params.get("export_format", "json")
        result = self._node_service.export(pk=pk, export_format=export_format)
        if result.errors is not None:
            return Response(
                {"errors": result.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        response = HttpResponse(result.content, content_type=result.content_type)
        response["Content-Disposition"] = f'attachment; filename="{result.filename}"'
        return response


class McpToolViewSet(OrgScopedViewSetMixin, CopyActionMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
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


class GraphOrganizationViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = GraphOrganization.objects.all()
    serializer_class = GraphOrganizationSerializer

    def perform_create(self, serializer):
        # Enforce the invariant: a flow's persistent-state row is always owned
        # by the flow's own org (never a different organization).
        self._assert_parent_in_active_org(serializer)
        serializer.save(organization_id=serializer.validated_data["graph"].org_id)

    def perform_update(self, serializer):
        serializer.save(organization_id=serializer.instance.graph.org_id)


class GraphOrganizationUserViewSet(
    OrgScopedChildViewSetMixin, viewsets.ReadOnlyModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = GraphOrganizationUser.objects.all()
    serializer_class = GraphOrganizationUserSerializer


class WebhookTriggerNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
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


class WebhookTriggerViewSet(OrgScopedQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    scope_distinct = True  # reverse join via trigger nodes can duplicate rows
    queryset = WebhookTrigger.objects.all()
    serializer_class = WebhookTriggerSerializer
    filter_backends = [DjangoFilterBackend]

    def get_org_scope_q(self, org_id: int) -> Q:
        # A standalone trigger has no org column; it is visible through the
        # flow(s) whose trigger nodes reference it.
        return Q(webhook_trigger_nodes__graph__org_id=org_id)


class TelegramTriggerNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = TelegramTriggerNode.objects.prefetch_related("fields")
    serializer_class = TelegramTriggerNodeSerializer


class ScheduleTriggerNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = ScheduleTriggerNode.objects.all()
    serializer_class = ScheduleTriggerNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph", "is_active", "run_mode"]


class GraphNoteViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = GraphNote.objects.all()
    serializer_class = GraphNoteSerializer


class NgrokWebhookConfigViewSet(SuperadminWriteMixin, ModelViewSet):
    # Global infrastructure config (ngrok tunnel/auth): readable by any
    # authenticated user, writable only by superadmins.
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


class LabelViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    queryset = Label.objects.all()
    serializer_class = LabelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "parent"]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        labels = list(queryset)

        # Build paths in memory (one extra lightweight query) to avoid N+1
        # and to correctly resolve parents that may be filtered out. Scoped to
        # the active org (the label tree never crosses orgs).
        id_to_row = {
            row["id"]: row
            for row in Label.objects.filter(org_id=self.get_active_org_id()).values(
                "id", "parent_id", "name"
            )
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
    # Global singleton holding the platform Twilio credentials (secret auth
    # token) — superadmin only, both read and write.
    permission_classes = [IsAuthenticated, IsSuperadmin]
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

    # Manages the platform Twilio account (uses the secret token) — superadmin only.
    permission_classes = [IsAuthenticated, IsSuperadmin]

    @extend_schema(**TWILIO_PHONE_NUMBERS_GET)
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

    # Manages the platform Twilio account (uses the secret token) — superadmin only.
    permission_classes = [IsAuthenticated, IsSuperadmin]

    @extend_schema(**TWILIO_CONFIGURE_WEBHOOK_POST)
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
