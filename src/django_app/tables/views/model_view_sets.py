import json
import logging
import uuid

logger = logging.getLogger(__name__)

from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.db.models import NOT_PROVIDED, Exists, IntegerField, OuterRef, Prefetch, Q
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
from tables.exceptions import (
    AgentSerializerError,
    BuiltInToolModificationError,
    BulkSaveValidationError,
    TaskSerializerError,
)
from tables.services.rbac.authentication import IsAuthenticatedOrApiKey
from tables.serializers.graph_bulk_save_serializers import GraphBulkSaveInputSerializer
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer
from tables.services.graph_bulk_save_service import GraphBulkSaveService
from tables.graph_versioning.services import GraphVersioningService
from tables.graph_versioning.serializers import (
    GraphVersionCreateSerializer,
    GraphVersionReadSerializer,
    GraphVersionUpdateSerializer,
    RestoreVersionInputSerializer,
)
from agents.serializers.surface_serializers import SurfaceReadSerializer
from agents.services.node_surface_service import NodeSurfaceService

from tables.import_export.enums import EntityType

from tables.models import (
    Agent,
    AgentNode,
    AgentNodeTask,
    AudioTranscriptionNode,
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
    Secret,
    StartNode,
    SubGraphNode,
    Task,
    TaskContext,
    TaskNode,
)
from tables.models.crew_models import (
    AgentMcpTools,
    AgentPythonCodeTools,
    AgentPythonCodeToolConfigs,
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
from tables.swagger_schemas.tools_schemas import (
    MCP_TOOL_BULK_DELETE_POST,
    MCP_TOOL_BULK_EXPORT_POST,
    MCP_TOOL_COPY_POST,
    MCP_TOOL_EXPORT_GET,
    MCP_TOOL_FAVORITE_DELETE,
    MCP_TOOL_FAVORITE_POST,
    MCP_TOOL_IMPORT_POST,
    PYTHON_CODE_TOOL_BULK_DELETE_POST,
    PYTHON_CODE_TOOL_BULK_EXPORT_POST,
    PYTHON_CODE_TOOL_COPY_POST,
    PYTHON_CODE_TOOL_EXPORT_GET,
    PYTHON_CODE_TOOL_FAVORITE_DELETE,
    PYTHON_CODE_TOOL_FAVORITE_POST,
    PYTHON_CODE_TOOL_IMPORT_POST,
    TOOL_ORDERING_PARAMETER,
)
from tables.swagger_schemas.tools_usage_schemas import (
    MCP_TOOL_USAGE_DETAIL_GET,
    MCP_TOOL_USAGE_POST,
    PYTHON_CODE_TOOL_USAGE_DETAIL_GET,
    PYTHON_CODE_TOOL_USAGE_POST,
)
from tables.services.tools_usage_service import (
    get_mcp_tool_usage_detail,
    get_python_code_tool_usage_detail,
)
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
from tables.models.favorite_models import McpToolFavorite, PythonCodeToolFavorite
from tables.models.python_models import PythonCodeToolConfig
from tables.models.realtime_models import (
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
    RealtimeSessionItem,
    OpenAIRealtimeConfig,
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    ConversationRecording,
)
from tables.filters import (
    EmbeddingModelFilter,
    LabelFilterBackend,
    LLMModelFilter,
    McpToolFilter,
    ProviderFilter,
    PythonCodeToolFilter,
)
from tables.utils.helpers import natural_sort_key
from tables.models.label_models import Label
from tables.models.vector_models import MemoryDatabase
from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    WebhookTrigger,
    RealtimeChannel,
    TwilioChannel,
    ProviderType,
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
    OrgScopedViewSetMixin,
    SuperadminWriteMixin,
    ToolUsageActionsMixin,
)
from tables.models.rbac_models import ApiKey, Organization
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.permissions import (
    HasOrgPermission,
    IsSuperadmin,
    IsSystemApiKeyAuthenticated,
    DenyApiKeyAuth,
)
from tables.serializers.org_scoped_fields import resolve_active_org_id
from tables.services.rbac.permission_action_map import DEFAULT_ACTION_MAP
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.secrets import secret_resolver, secret_usage_service
from tables.swagger_schemas.secret_schemas import SECRET_USAGE_GET
from tables.serializers.model_serializers.node_serializers.flow_control_serializers import (
    validate_classification_condition_group_names,
)
from tables.serializers.utils.mixins import assert_node_ref_in_graph
from tables.serializers.model_serializers import (
    AgentNodeSerializer,
    AgentNodeTaskSerializer,
    AgentReadSerializer,
    ClassificationDecisionTableNodeSerializer,
    AgentWriteSerializer,
    AudioTranscriptionNodeSerializer,
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
    ProviderSerializer,
    PythonCodeResultSerializer,
    PythonCodeToolConfigSerializer,
    PythonCodeToolSerializer,
    PythonNodeSerializer,
    ConversationRecordingSerializer,
    ElevenLabsRealtimeConfigSerializer,
    GeminiRealtimeConfigSerializer,
    OpenAIRealtimeConfigSerializer,
    RealtimeAgentChatSerializer,
    RealtimeAgentReadSerializer,
    RealtimeAgentWriteSerializer,
    RealtimeChannelInternalSerializer,
    RealtimeChannelSerializer,
    RealtimeConfigSerializer,
    RealtimeModelSerializer,
    RealtimeAgentDefinitionSerializer,
    RealtimeSessionItemSerializer,
    RealtimeTranscriptionConfigSerializer,
    RealtimeTranscriptionModelSerializer,
    TwilioChannelSerializer,
    SecretSerializer,
    StartNodeSerializer,
    SubGraphNodeSerializer,
    TaskNodeSerializer,
    TaskReadSerializer,
    TaskWriteSerializer,
    WebhookTriggerNodeSerializer,
    WebhookTriggerNodeReadSerializer,
    ScheduleTriggerNodeSerializer,
    TelegramTriggerNodeSerializer,
    TelegramTriggerNodeReadSerializer,
)

from tables.serializers.serializers import (
    BulkDeleteRequestSerializer,
    BulkExportSerializer,
    GraphNodesPartialExportSerializer,
    ImportRequestSerializer,
)
from tables.services import (
    agent_delete_service,
    crew_delete_service,
    embedding_config_delete_service,
    graph_delete_service,
    llm_config_delete_service,
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
from tables.services.twilio_service import TwilioService, TwilioServiceError
from tables.services.import_export_service import ViewSetImportExportService
from tables.services.classification_decision_table_node_service import (
    ClassificationDecisionTableNodeService,
)
from tables.import_export.services.import_service import ImportSettings
from tables.services.redis_service import RedisService
from tables.swagger_schemas.twilio_schemas import (
    TWILIO_CONFIGURE_WEBHOOK_POST,
    TWILIO_CHANNEL_PHONE_NUMBERS_GET,
    REALTIME_CHANNEL_LOOKUP_BY_TOKEN_GET,
)
from tables.swagger_schemas.webhook_schemas import (
    WEBHOOK_TRIGGER_NODE_CREATE,
    WEBHOOK_TRIGGER_NODE_UPDATE,
    WEBHOOK_TRIGGER_NODE_PARTIAL_UPDATE,
)
from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.services.rbac.org_context_service import OrgContextService
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


class LLMConfigReadWriteViewSet(OrgScopedViewSetMixin, ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "bulk_delete": Permission.DELETE}

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

    queryset = LLMConfig.objects.select_related("api_key_secret").all()
    serializer_class = LLMConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = LLMConfigFilter

    def perform_destroy(self, instance):
        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(self.request.user, org_id)
        llm_config_delete_service.assert_llm_config_deletable(instance, org_id, effective)
        instance.delete()

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = BulkDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        dry_run = serializer.validated_data["dry_run"]

        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(request.user, org_id)
        result = llm_config_delete_service.bulk_delete_llm_configs(
            ids, org_id, effective, dry_run=dry_run
        )

        status_code = (
            status.HTTP_200_OK
            if not result["not_found_ids"] and not result["skipped_ids"]
            else status.HTTP_207_MULTI_STATUS
        )
        return Response(result, status=status_code)


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
    rbac_action_map = {**DEFAULT_ACTION_MAP, "bulk_delete": Permission.DELETE}

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

    queryset = EmbeddingConfig.objects.select_related("api_key_secret").all()
    serializer_class = EmbeddingConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = EmbeddingConfigFilter

    def perform_destroy(self, instance):
        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(self.request.user, org_id)
        embedding_config_delete_service.assert_embedding_config_deletable(
            instance, org_id, effective
        )
        instance.delete()

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = BulkDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        dry_run = serializer.validated_data["dry_run"]

        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(request.user, org_id)
        result = embedding_config_delete_service.bulk_delete_embedding_configs(
            ids, org_id, effective, dry_run=dry_run
        )

        status_code = (
            status.HTTP_200_OK
            if not result["not_found_ids"] and not result["skipped_ids"]
            else status.HTTP_207_MULTI_STATUS
        )
        return Response(result, status=status_code)


class AgentViewSet(OrgScopedViewSetMixin, CopyActionMixin, ModelViewSet):
    """
    DEPRECATED: AgentViewSet is deprecated. Use agents.AgentDefinition +
    AgentNode endpoints instead. Exists only for backward compatibility with
    existing Agent rows.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
        "bulk_delete": Permission.DELETE,
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
            from django.db.models import Q

            queryset = queryset.filter(
                realtime_agent__isnull=False,
            ).filter(
                Q(realtime_agent__openai_config__isnull=False)
                | Q(realtime_agent__elevenlabs_config__isnull=False)
                | Q(realtime_agent__gemini_config__isnull=False)
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
        request={"multipart/form-data": ImportRequestSerializer},
        responses={
            200: OpenApiResponse(
                description="Import summary with created/skipped entity counts"
            )
        },
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

    def perform_destroy(self, instance):
        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(self.request.user, org_id)
        agent_delete_service.assert_agent_deletable(instance, org_id, effective)
        instance.delete()

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = BulkDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        dry_run = serializer.validated_data["dry_run"]

        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(request.user, org_id)
        result = agent_delete_service.bulk_delete_agents(
            ids, org_id, effective, dry_run=dry_run
        )

        status_code = (
            status.HTTP_200_OK
            if not result["not_found_ids"] and not result["skipped_ids"]
            else status.HTTP_207_MULTI_STATUS
        )
        return Response(result, status=status_code)


class CrewReadWriteViewSet(OrgScopedViewSetMixin, CopyActionMixin, ModelViewSet):
    """
    DEPRECATED: CrewReadWriteViewSet is deprecated. Use the new Agent/Task
    graph node endpoints (AgentNode, TaskNode) instead. Exists only for
    backward compatibility with existing Crew rows.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.PROJECTS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
        "bulk_delete": Permission.DELETE,
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

    def perform_destroy(self, instance):
        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(self.request.user, org_id)
        crew_delete_service.assert_crew_deletable(instance, org_id, effective)
        instance.delete()

    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(self.get_object())

    @extend_schema(
        request={"multipart/form-data": ImportRequestSerializer},
        responses={
            200: OpenApiResponse(
                description="Import summary with created/skipped entity counts"
            )
        },
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

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = BulkDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        dry_run = serializer.validated_data["dry_run"]

        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(request.user, org_id)
        result = crew_delete_service.bulk_delete_crews(
            ids, org_id, effective, dry_run=dry_run
        )

        status_code = (
            status.HTTP_200_OK
            if not result["not_found_ids"] and not result["skipped_ids"]
            else status.HTTP_207_MULTI_STATUS
        )
        return Response(result, status=status_code)


class TaskReadWriteViewSet(OrgScopedChildViewSetMixin, ModelViewSet):
    """
    DEPRECATED: TaskReadWriteViewSet is deprecated. Use TaskNode/AgentNodeTask
    endpoints instead. Exists only for backward compatibility with existing
    Task rows.
    """

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


@extend_schema_view(
    copy=extend_schema(**PYTHON_CODE_TOOL_COPY_POST),
    list=extend_schema(parameters=[TOOL_ORDERING_PARAMETER]),
)
class PythonCodeToolViewSet(
    OrgScopedHybridViewSetMixin,
    CopyActionMixin,
    ToolUsageActionsMixin,
    viewsets.ModelViewSet,
):
    """
    A viewset for viewing and editing PythonCodeTool instances.
    Built-in tools are global; custom tools are org-owned.
    Prevents modifications or deletions of built-in tools.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "bulk_delete": Permission.DELETE,
        "usage": Permission.READ,
        "usage_detail": Permission.READ,
        "favorite": Permission.READ,
        "export": Permission.EXPORT,
        "bulk_export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
    }
    global_visibility_q = Q(built_in=True)
    custom_create_values = {"built_in": False}

    copy_service_class = PythonCodeToolCopyService
    copy_serializer_class = PythonCodeToolSerializer

    queryset = PythonCodeTool.objects.all().select_related("python_code")
    serializer_class = PythonCodeToolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = PythonCodeToolFilter

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.PYTHON_CODE_TOOL,
            export_prefix="python_code_tool",
            filename_attr="name",
        )

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .annotate(
                is_favorite=Exists(
                    PythonCodeToolFavorite.objects.filter(
                        user=self.request.user, tool=OuterRef("pk")
                    )
                )
            )
        )
        ordering = ["-id"]
        if self.request.query_params.get("ordering") == "favorite":
            ordering = ["-is_favorite", "-id"]
        return queryset.order_by(*ordering)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.built_in:
            raise BuiltInToolModificationError()
        return super().destroy(request, *args, **kwargs)

    @extend_schema(methods=["POST"], **PYTHON_CODE_TOOL_FAVORITE_POST)
    @extend_schema(methods=["DELETE"], **PYTHON_CODE_TOOL_FAVORITE_DELETE)
    @action(detail=True, methods=["post", "delete"], url_path="favorite")
    def favorite(self, request, pk=None):
        tool = self.get_object()
        if request.method == "POST":
            PythonCodeToolFavorite.objects.get_or_create(user=request.user, tool=tool)
        else:
            PythonCodeToolFavorite.objects.filter(user=request.user, tool=tool).delete()
        return Response(status=status.HTTP_200_OK)

    @extend_schema(**PYTHON_CODE_TOOL_BULK_DELETE_POST)
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response(
                {"detail": "ids must be a list of integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # Built-in tools are silently excluded, never rejected — they are
            # simply not part of the deletable queryset (org_id also filters
            # them out since built-ins have org_id=None, but built_in=False
            # is kept explicit for clarity/defense-in-depth).
            tool_list = PythonCodeTool.objects.filter(
                id__in=ids,
                org_id=self.get_active_org_id(),
                built_in=False,
            )
            deleted_count = tool_list.count()
            for tool in tool_list:
                tool.delete()

        return Response(
            {"deleted": deleted_count, "ids": ids}, status=status.HTTP_200_OK
        )

    @extend_schema(**PYTHON_CODE_TOOL_USAGE_POST)
    @action(detail=False, methods=["post"], url_path="usage")
    def usage(self, request):
        return self._usage_response(request, PythonCodeTool)

    @extend_schema(**PYTHON_CODE_TOOL_USAGE_DETAIL_GET)
    @action(detail=True, methods=["get"], url_path="usage-detail")
    def usage_detail(self, request, pk=None):
        return self._usage_detail_response(
            pk, get_python_code_tool_usage_detail, "PythonCodeTool"
        )

    @extend_schema(**PYTHON_CODE_TOOL_EXPORT_GET)
    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(
            self.get_object(), org_id=self.get_active_org_id()
        )

    @extend_schema(**PYTHON_CODE_TOOL_BULK_EXPORT_POST)
    @action(detail=False, methods=["post"], url_path="bulk-export")
    def bulk_export(self, request):
        serializer = BulkExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity_ids = serializer.validated_data["ids"]

        # Built-in tools (org_id=None) are globally visible and must be
        # exportable like any org's own tool, mirroring get_org_scope_q()
        # used by the import/export strategy and the get_queryset() scoping
        # that export/get_object() already relies on.
        existing_ids = PythonCodeTool.objects.filter(
            Q(built_in=True) | Q(org_id=self.get_active_org_id()),
            id__in=entity_ids,
        ).values_list("id", flat=True)
        if len(existing_ids) != len(entity_ids):
            return Response(
                {"message": "Some entity IDs do not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return self.import_export_service.bulk_export(
            entity_ids, org_id=self.get_active_org_id()
        )

    @extend_schema(**PYTHON_CODE_TOOL_IMPORT_POST)
    @action(detail=False, methods=["post"], url_path="import")
    def import_entity(self, request):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)
        vd = file_serializer.validated_data
        data = self.import_export_service.import_entity(
            vd["file"],
            user=request.user,
            settings=ImportSettings(import_labels=vd["import_labels"]),
            org_id=self.get_active_org_id(),
        )
        return Response(data, status=status.HTTP_200_OK)


class PythonCodeToolConfigViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    queryset = PythonCodeToolConfig.objects.select_related("tool")
    serializer_class = PythonCodeToolConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["tool", "name"]


class PythonCodeResultReadViewSet(
    OrgScopedViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    queryset = PythonCodeResult.objects.all()
    serializer_class = PythonCodeResultSerializer


class GraphViewSet(OrgScopedViewSetMixin, CopyActionMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "export": Permission.EXPORT,
        "bulk_export": Permission.EXPORT,
        "partial_export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
        "partial_import": Permission.UPDATE,
        "save_flow": Permission.UPDATE,
        "bulk_delete": Permission.DELETE,
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
                    "task_node_list",
                    queryset=TaskNode.objects.select_related(
                        "inline_surface"
                    ).prefetch_related(
                        "surface_list",
                        "inline_surface__python_tools",
                        "inline_surface__mcp_tools",
                        "inline_surface__storage_items",
                        "inline_surface__knowledge__naive_search_config",
                        "inline_surface__knowledge__graph_basic_search_config",
                        "inline_surface__knowledge__graph_local_search_config",
                    ),
                ),
                Prefetch(
                    "agent_node_list",
                    queryset=AgentNode.objects.select_related(
                        "inline_surface"
                    ).prefetch_related(
                        "surface_list",
                        "tasks",
                        "tasks__context_tasks",
                        "inline_surface__python_tools",
                        "inline_surface__mcp_tools",
                        "inline_surface__storage_items",
                        "inline_surface__knowledge__naive_search_config",
                        "inline_surface__knowledge__graph_basic_search_config",
                        "inline_surface__knowledge__graph_local_search_config",
                    ),
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

    def perform_destroy(self, instance):
        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(self.request.user, org_id)
        graph_delete_service.assert_graph_deletable(instance, org_id, effective)
        instance.delete()

    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(self.get_object())

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        serializer = BulkDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        dry_run = serializer.validated_data["dry_run"]

        org_id = self.get_active_org_id()
        effective = PermissionResolver().resolve(request.user, org_id)
        result = graph_delete_service.bulk_delete_graphs(
            ids, org_id, effective, dry_run=dry_run
        )

        status_code = (
            status.HTTP_200_OK
            if not result["not_found_ids"] and not result["skipped_ids"]
            else status.HTTP_207_MULTI_STATUS
        )
        return Response(result, status=status_code)

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

    @extend_schema(
        request={"multipart/form-data": ImportRequestSerializer},
        responses={
            200: OpenApiResponse(
                description="Import summary with created/skipped entity counts"
            )
        },
    )
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
        org_id = self.get_active_org_id()
        effective_permissions = PermissionResolver().resolve(
            user=request.user, org_id=org_id
        )
        partial_import_service = PartialImportService(entity_registry)
        id_mapper = partial_import_service.import_data(
            export_data=data,
            graph=graph,
            org_id=org_id,
            user=request.user,
            effective_permissions=effective_permissions,
        )
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
    list=extend_schema(
        description=(
            "Returns a paginated list of graph versions for the given graph. "
            "Soft-deleted versions are excluded. "
            "Use the `graph_id` query parameter to filter by a specific graph."
        ),
        parameters=[
            OpenApiParameter(
                name="graph_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter versions by graph ID.",
            )
        ],
    ),
    restore=extend_schema(
        summary="Restore the graph to the state captured in this version, with optional auto-backup before restoring.",
        description=(
            "Restores the target graph to the exact state stored in this version's snapshot. "
            "Before applying the snapshot, the service validates that all external dependencies "
            "(LLMs, tools, knowledge sources) referenced in the snapshot are still available; "
            "any that are missing are stripped and reported in the `warnings` list. "
            "If the `backup` query parameter is `true`, the current graph state is saved as a new "
            "version before restoring, and its ID is returned in `auto_backup_version_id`. "
            "Uses optimistic locking via `save_version` to prevent overwriting concurrent edits."
        ),
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
        summary="Create a new independent graph from this version's snapshot.",
        description=(
            "Creates a new, fully independent graph from the snapshot stored in this version. "
            "The new graph is a copy — it does not remain linked to the original. "
            "Missing dependencies are stripped from the snapshot and reported in `warnings`. "
            "Returns the ID of the newly created graph."
        ),
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
    all=extend_schema(
        summary="List all graph versions including soft-deleted ones.",
        description=(
            "Returns all graph versions including those that have been soft-deleted. "
            "Intended for audit or recovery workflows where deleted versions need to be visible. "
            "Use the `graph_id` query parameter to scope results to a specific graph."
        ),
        responses={200: GraphVersionReadSerializer(many=True)},
        parameters=[
            OpenApiParameter(
                name="graph_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter versions by graph ID.",
            )
        ],
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
    """
    DEPRECATED: CrewNodeViewSet is deprecated. Use AgentNodeViewSet or
    TaskNodeViewSet instead. Exists only for backward compatibility with
    existing CrewNode rows.
    """

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


class TaskNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "combine": Permission.READ}
    org_filter_path = "graph__org_id"
    queryset = TaskNode.objects.select_related("inline_surface").prefetch_related(
        "surface_list",
        "inline_surface__python_tools",
        "inline_surface__mcp_tools",
        "inline_surface__storage_items",
        "inline_surface__knowledge__naive_search_config",
        "inline_surface__knowledge__graph_basic_search_config",
        "inline_surface__knowledge__graph_local_search_config",
    )
    serializer_class = TaskNodeSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["organization"] = Organization.objects.get(id=self.get_active_org_id())
        return context

    def perform_update(self, serializer):
        # The serializer allows writing `graph`; without this check a PATCH
        # could move the node into another org's graph.
        self._assert_parent_in_active_org(serializer)
        super().perform_update(serializer)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=SurfaceReadSerializer,
                description="Combined surface data merged from the node's "
                "attached surfaces and inline surface.",
            ),
            400: OpenApiResponse(description="Conflicting RAG configs."),
        },
    )
    @action(detail=True, methods=["get"], url_path="combine")
    def combine(self, request, pk=None):
        node = self.get_object()
        combined = NodeSurfaceService.build_combined_surface(node)
        return Response(combined, status=status.HTTP_200_OK)


class AgentNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "combine": Permission.READ}
    org_filter_path = "graph__org_id"
    queryset = AgentNode.objects.select_related("inline_surface").prefetch_related(
        "surface_list",
        "tasks",
        "tasks__context_tasks",
        "inline_surface__python_tools",
        "inline_surface__mcp_tools",
        "inline_surface__storage_items",
        "inline_surface__knowledge__naive_search_config",
        "inline_surface__knowledge__graph_basic_search_config",
        "inline_surface__knowledge__graph_local_search_config",
    )
    serializer_class = AgentNodeSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["organization"] = Organization.objects.get(id=self.get_active_org_id())
        return context

    def perform_update(self, serializer):
        # The serializer allows writing `graph`; without this check a PATCH
        # could move the node into another org's graph.
        self._assert_parent_in_active_org(serializer)
        super().perform_update(serializer)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=SurfaceReadSerializer,
                description="Combined surface data merged from the node's "
                "attached surfaces and inline surface.",
            ),
            400: OpenApiResponse(description="Conflicting RAG configs."),
        },
    )
    @action(detail=True, methods=["get"], url_path="combine")
    def combine(self, request, pk=None):
        node = self.get_object()
        combined = NodeSurfaceService.build_combined_surface(node)
        return Response(combined, status=status.HTTP_200_OK)


class AgentNodeTaskViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "agent_node__graph__org_id"
    queryset = AgentNodeTask.objects.all()
    serializer_class = AgentNodeTaskSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["agent_node"]

    def _clean_and_save(self, serializer):
        instance = serializer.save()
        try:
            instance.full_clean()
        except ValidationError as error:
            raise serializers.ValidationError(
                error.message_dict if hasattr(error, "message_dict") else error.messages
            )

    @transaction.atomic
    def perform_create(self, serializer):
        # Parent org lives on agent_node.graph, so the mixin's default assert
        # (which reads parent.org_id) does not apply — check explicitly.
        agent_node = serializer.validated_data.get("agent_node")
        if agent_node is not None and (
            agent_node.graph.org_id != self.get_active_org_id()
        ):
            raise NotFound()
        self._clean_and_save(serializer)

    @transaction.atomic
    def perform_update(self, serializer):
        # Parent org lives on agent_node.graph — same reasoning as
        # perform_create: a PATCH could otherwise reassign agent_node to
        # another org's parent.
        agent_node = serializer.validated_data.get("agent_node")
        if agent_node is not None and (
            agent_node.graph.org_id != self.get_active_org_id()
        ):
            raise NotFound()
        self._clean_and_save(serializer)


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
    # NOTE: this endpoint is scheduled for removal. Until then it is locked to
    # superadmin
    permission_classes = [IsAuthenticated, IsSuperadmin]
    queryset = MemoryDatabase.objects.all()
    serializer_class = MemorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = MemoryFilter


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

    queryset = RealtimeConfig.objects.select_related("api_key_secret").all()
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

    queryset = RealtimeTranscriptionConfig.objects.select_related(
        "api_key_secret"
    ).all()
    serializer_class = RealtimeTranscriptionConfigSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = RealtimeTranscriptionConfigFilter


class RealtimeSessionItemViewSet(OrgScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    # Realtime session items hold conversation payloads (incl. base64 audio).
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.VOICE
    queryset = RealtimeSessionItem.objects.all()
    serializer_class = RealtimeSessionItemSerializer


@extend_schema_view(
    create=extend_schema(
        request=RealtimeAgentWriteSerializer,
        responses={201: RealtimeAgentReadSerializer},
    ),
    update=extend_schema(
        request=RealtimeAgentWriteSerializer,
        responses={200: RealtimeAgentReadSerializer},
    ),
    partial_update=extend_schema(
        request=RealtimeAgentWriteSerializer,
        responses={200: RealtimeAgentReadSerializer},
    ),
)
class RealtimeAgentViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    org_filter_path = "agent__org_id"
    queryset = RealtimeAgent.objects.all()

    def get_serializer_class(self):
        # На чтение (GET) отдаем полные объекты
        if self.action in ["list", "retrieve"]:
            return RealtimeAgentReadSerializer
        return RealtimeAgentWriteSerializer

    def create(self, request, *args, **kwargs):
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        instance = write_serializer.save()

        read_serializer = RealtimeAgentReadSerializer(
            instance, context={"request": self.request}
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        write_serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        if getattr(instance, "_prefetched_objects_cache", None):
            instance._prefetched_objects_cache = {}

        read_serializer = RealtimeAgentReadSerializer(
            instance, context={"request": self.request}
        )
        return Response(read_serializer.data)


class RealtimeAgentDefinitionViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    org_filter_path = "agent_definition__organization_id"
    queryset = RealtimeAgentDefinition.objects.all()
    serializer_class = RealtimeAgentDefinitionSerializer


class RealtimeAgentChatViewSet(OrgScopedChildViewSetMixin, ReadOnlyModelViewSet):
    """
    ViewSet for reading and deleting RealtimeAgentChat instances.

    Scoped through the chat's realtime agent to its agent's org. Chats whose
    rt_agent is NULL (orphaned) are not visible — acceptable for chat history.
    """

    rbac_resource_type = ResourceType.VOICE
    org_filter_path = "rt_agent__agent__org_id"
    queryset = RealtimeAgentChat.objects.all()
    serializer_class = RealtimeAgentChatSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["rt_agent", "rt_agent_definition"]
    permission_classes = [IsAuthenticatedOrApiKey]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(
            {"detail": "Deleted successfully"}, status=status.HTTP_204_NO_CONTENT
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="end",
        permission_classes=[IsSystemApiKeyAuthenticated],
    )
    def end(self, request):
        """Mark a RealtimeAgentChat as ended.

        Called server-to-server by the `realtime`/`voice_app` services
        (`voice_call_service._patch_agent_chat`) once a call ends. That caller
        has no logged-in user/org context and identifies the target chat by
        its opaque `connection_key` alone, so this action cannot be scoped
        through `self.get_queryset()` (which requires an active org via
        `OrgContextService`/`X-Organization-Id`) the way `destroy`/`retrieve`
        are.

        Restricted to `key_type=SYSTEM` API-key callers
        (`IsSystemApiKeyAuthenticated`)
        `RealtimeChannelViewSet.lookup_by_token` / `InitRealtimeAPIView`. Do
        not widen this to `IsAuthenticated` or the class-level
        `IsAuthenticatedOrApiKey`: either would let a caller who has no
        relationship to the chat's org (a plain JWT session, or a self-issued
        `key_type=USER` API key any org member can mint) end/mutate another
        org's realtime chat by guessing/observing its `connection_key`, since
        the lookup below performs no org filter of its own.
        """
        from django.utils import timezone

        connection_key = request.data.get("connection_key")
        if not connection_key:
            return Response(
                {"detail": "connection_key required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            chat = RealtimeAgentChat.objects.get(connection_key=connection_key)
        except RealtimeAgentChat.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        chat.ended_at = timezone.now()
        chat.duration_seconds = request.data.get("duration_seconds")
        chat.end_reason = request.data.get("end_reason", "completed")
        chat.save(update_fields=["ended_at", "duration_seconds", "end_reason"])
        return Response({"detail": "Updated"})


class OpenAIRealtimeConfigViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    queryset = OpenAIRealtimeConfig.objects.all()
    serializer_class = OpenAIRealtimeConfigSerializer


class ElevenLabsRealtimeConfigViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    queryset = ElevenLabsRealtimeConfig.objects.all()
    serializer_class = ElevenLabsRealtimeConfigSerializer


class GeminiRealtimeConfigViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    queryset = GeminiRealtimeConfig.objects.all()
    serializer_class = GeminiRealtimeConfigSerializer


class RealtimeChannelViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]

    rbac_resource_type = ResourceType.VOICE
    rbac_action_map = {**DEFAULT_ACTION_MAP}

    queryset = RealtimeChannel.objects.select_related(
        "twilio__webhook_trigger__ngrok",
        "twilio__webhook_trigger__localhost",
    ).all()
    serializer_class = RealtimeChannelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["realtime_agent", "channel_type", "is_active", "token"]

    @extend_schema(**REALTIME_CHANNEL_LOOKUP_BY_TOKEN_GET)
    @action(
        detail=False,
        methods=["get"],
        url_path="lookup-by-token",
        permission_classes=[IsSystemApiKeyAuthenticated],
    )
    def lookup_by_token(self, request):
        """Resolve a channel by its unique `token`, unscoped by org.

        Used only by the `realtime`/`voice_app` services to route an inbound
        Twilio call (POST /voice/{token}) to the right agent — that caller has
        no logged-in user and cannot supply `X-Organization-Id`. The token
        itself (an unguessable UUID) is the lookup/authorization key, so the
        normal `HasOrgPermission` + `OrgScopedViewSetMixin.get_queryset` org
        filter is deliberately bypassed here.
        """
        raw_token = request.query_params.get("token")
        if not raw_token:
            return Response(
                {"error": "token is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            token = uuid.UUID(str(raw_token))
        except (ValueError, AttributeError, TypeError):
            return Response(status=status.HTTP_404_NOT_FOUND)

        channel = (
            RealtimeChannel.objects.select_related(
                "twilio__webhook_trigger__ngrok",
                "twilio__webhook_trigger__localhost",
            )
            .filter(token=token)
            .first()
        )
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(RealtimeChannelInternalSerializer(channel).data)


class TwilioChannelViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    org_filter_path = "channel__org_id"
    queryset = TwilioChannel.objects.select_related(
        "webhook_trigger__ngrok", "webhook_trigger__localhost"
    )
    rbac_resource_type = ResourceType.VOICE
    rbac_action_map = {**DEFAULT_ACTION_MAP, "phone_numbers": Permission.READ}
    serializer_class = TwilioChannelSerializer

    def create(self, request, *args, **kwargs):
        channel_id = request.data.get("channel")
        instance = TwilioChannel.objects.filter(channel_id=channel_id).first()
        if instance:
            serializer = self.get_serializer(instance, data=request.data)
            serializer.is_valid(raise_exception=True)
            self._assert_parent_in_active_org(serializer)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    @extend_schema(**TWILIO_CHANNEL_PHONE_NUMBERS_GET)
    @action(detail=False, methods=["get"], url_path="phone-numbers")
    def phone_numbers(self, request, pk=None):
        """Return this channel's Twilio incoming phone numbers."""

        sid = request.query_params.get("sid")
        auth_token_secret_id = request.query_params.get("auth_token_secret_id")

        if not sid or not auth_token_secret_id:
            return Response(
                {
                    "error": "Both 'sid' and 'auth_token_secret_id' query parameters are required"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            TwilioService().validate_account_sid(sid)
            auth_token = secret_resolver.resolve(
                secret_id=auth_token_secret_id,
                org_id=resolve_active_org_id(request),
                context="TwilioChannel.auth_token",
            )
            numbers = TwilioService().get_phone_numbers(sid, auth_token)
        except TwilioServiceError as e:
            return Response({"error": e.message}, status=e.status_code)

        return Response({"results": numbers})


class ConversationRecordingViewSet(OrgScopedChildViewSetMixin, viewsets.ModelViewSet):
    """
    Scoped through the recording's chat -> realtime agent to its agent's org
    (mirrors RealtimeAgentChatViewSet's scoping). Recordings whose chat has no
    rt_agent (orphaned) are not visible — same accepted trade-off as chat history.

    `create` is reachable two ways:
    - An authenticated org member (JWT) or a self-issued USER API key, sending
      `X-Organization-Id` as usual — org-scoping is enforced via
      `_assert_parent_in_active_org` exactly like any other child resource.
    - The `realtime`/`voice_app` services (`voice_call_service._post_recording`),
      authenticated with a `key_type=SYSTEM` API key, once a call ends. That
      caller has no logged-in user/org context and can never supply
      `X-Organization-Id`, and identifies its target purely by the opaque
      `connection_key` — same trust model as `RealtimeAgentChatViewSet.end`.
      For that caller only, `_assert_parent_in_active_org` is skipped (the
      SYSTEM key itself is the authorization check); a self-issued USER key
      still goes through the normal org check, so it cannot attach a
      recording to another org's chat by guessing a `connection_key`.
    """

    queryset = ConversationRecording.objects.all()
    serializer_class = ConversationRecordingSerializer
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["rt_agent_chat", "recording_type"]
    rbac_resource_type = ResourceType.VOICE
    org_filter_path = "rt_agent_chat__rt_agent__agent__org_id"
    permission_classes = [IsAuthenticatedOrApiKey]

    def _is_system_api_key_request(self) -> bool:
        return (
            isinstance(self.request.auth, ApiKey)
            and self.request.auth.key_type == ApiKey.KeyType.SYSTEM
        )

    def perform_create(self, serializer):
        file = self.request.FILES.get("file")
        file_size = file.size if file else None
        audio_format = "wav"

        # Allow creating by connection_key (used by the realtime service)
        connection_key = self.request.data.get("connection_key")
        rt_agent_chat = None
        if connection_key:
            try:
                rt_agent_chat = RealtimeAgentChat.objects.get(
                    connection_key=connection_key
                )
            except RealtimeAgentChat.DoesNotExist:
                from rest_framework.exceptions import (
                    ValidationError as DRFValidationError,
                )

                raise DRFValidationError(
                    {"connection_key": "No matching RealtimeAgentChat found"}
                )
            serializer.validated_data["rt_agent_chat"] = rt_agent_chat

        # A trusted SYSTEM API key (the realtime/voice_app services) has no
        # X-Organization-Id to check against — skip the org assertion for it,
        # same trust boundary as RealtimeAgentChatViewSet.end. Any other
        # caller (JWT session or a self-issued USER key) still goes through
        # the normal parent-org check.
        if not self._is_system_api_key_request():
            self._assert_parent_in_active_org(serializer)

        serializer.save(
            file_size=file_size,
            audio_format=audio_format,
            **({"rt_agent_chat": rt_agent_chat} if rt_agent_chat is not None else {}),
        )


def _load_realtime_voices() -> dict:
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent / "static" / "realtime_voices.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


_REALTIME_VOICES = _load_realtime_voices()


class RealtimeVoicesView(generics.GenericAPIView):
    """Return static list of available voices per realtime provider."""

    # Response body is a static constant (loaded from realtime_voices.json
    # at import time) — no DB access, no queryset to scope.
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.VOICE
    action = "retrieve"

    def get(self, request, *args, **kwargs):
        return Response(_REALTIME_VOICES)


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

        # Org isolation: each condition group's next_node_id must reference a node
        # in this decision table's own graph (⇒ same org). Condition groups are
        # created here rather than by the serializer (they're popped from `data`
        # before validation), so the same same-graph check the serializer applies
        # to default_next_node_id / next_error_node_id is enforced here too. A
        # cross-graph, cross-org, or non-existent id is rejected identically
        # ("Invalid pk ..."), so existence never leaks
        for group in condition_groups_data or []:
            assert_node_ref_in_graph(
                group.get("next_node_id"), node.graph, "condition_groups.next_node_id"
            )

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


class ClassificationDecisionTableNodeModelViewSet(
    OrgScopedChildViewSetMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "export": Permission.EXPORT}
    org_filter_path = "graph__org_id"
    queryset = ClassificationDecisionTableNode.objects.all()
    serializer_class = ClassificationDecisionTableNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._node_service = ClassificationDecisionTableNodeService()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        node, _ = self._node_service.create_or_update(
            data=request.data, request=request
        )
        return Response(self.get_serializer(node).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        node, _ = self._node_service.create_or_update(
            data=request.data,
            instance=instance,
            partial=partial,
            request=request,
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
        result = self._node_service.export(
            pk=pk, export_format=export_format, org_id=self.get_active_org_id()
        )
        if result.errors is not None:
            return Response(
                {"errors": result.errors}, status=status.HTTP_400_BAD_REQUEST
            )

        response = HttpResponse(result.content, content_type=result.content_type)
        response["Content-Disposition"] = f'attachment; filename="{result.filename}"'
        return response


@extend_schema_view(
    copy=extend_schema(**MCP_TOOL_COPY_POST),
    list=extend_schema(parameters=[TOOL_ORDERING_PARAMETER]),
)
class McpToolViewSet(
    OrgScopedViewSetMixin, CopyActionMixin, ToolUsageActionsMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        "copy": Permission.CREATE,
        "bulk_delete": Permission.DELETE,
        "usage": Permission.READ,
        "usage_detail": Permission.READ,
        "favorite": Permission.READ,
        "export": Permission.EXPORT,
        "bulk_export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
    }
    copy_service_class = McpToolCopyService
    copy_serializer_class = McpToolSerializer

    queryset = McpTool.objects.select_related("auth_secret").all()
    serializer_class = McpToolSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = McpToolFilter

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.MCP_TOOL,
            export_prefix="mcp_tool",
            filename_attr="name",
        )

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .annotate(
                is_favorite=Exists(
                    McpToolFavorite.objects.filter(
                        user=self.request.user, tool=OuterRef("pk")
                    )
                )
            )
        )
        ordering = ["-id"]
        if self.request.query_params.get("ordering") == "favorite":
            ordering = ["-is_favorite", "-id"]
        return queryset.order_by(*ordering)

    @extend_schema(methods=["POST"], **MCP_TOOL_FAVORITE_POST)
    @extend_schema(methods=["DELETE"], **MCP_TOOL_FAVORITE_DELETE)
    @action(detail=True, methods=["post", "delete"], url_path="favorite")
    def favorite(self, request, pk=None):
        tool = self.get_object()
        if request.method == "POST":
            McpToolFavorite.objects.get_or_create(user=request.user, tool=tool)
        else:
            McpToolFavorite.objects.filter(user=request.user, tool=tool).delete()
        return Response(status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        # PUT is a full-replace: any concrete field missing from the body is
        # explicitly back-filled with its model default (or None) so a bare
        # PUT clears unspecified fields instead of silently keeping stale
        # values. This must NOT run for PATCH — partial_update overrides it
        # below so a partial body (e.g. {"labels": [...]}) isn't forced
        # through this full-replace path and doesn't get its other required
        # fields nulled out.
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

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @extend_schema(**MCP_TOOL_BULK_DELETE_POST)
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response(
                {"detail": "ids must be a list of integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # McpTool has no built-in concept — every matching id is deletable.
            tool_list = McpTool.objects.filter(
                id__in=ids, org_id=self.get_active_org_id()
            )
            deleted_count = tool_list.count()
            for tool in tool_list:
                tool.delete()

        return Response(
            {"deleted": deleted_count, "ids": ids}, status=status.HTTP_200_OK
        )

    @extend_schema(**MCP_TOOL_USAGE_POST)
    @action(detail=False, methods=["post"], url_path="usage")
    def usage(self, request):
        return self._usage_response(request, McpTool)

    @extend_schema(**MCP_TOOL_USAGE_DETAIL_GET)
    @action(detail=True, methods=["get"], url_path="usage-detail")
    def usage_detail(self, request, pk=None):
        return self._usage_detail_response(pk, get_mcp_tool_usage_detail, "McpTool")

    @extend_schema(**MCP_TOOL_EXPORT_GET)
    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(
            self.get_object(), org_id=self.get_active_org_id()
        )

    @extend_schema(**MCP_TOOL_BULK_EXPORT_POST)
    @action(detail=False, methods=["post"], url_path="bulk-export")
    def bulk_export(self, request):
        serializer = BulkExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity_ids = serializer.validated_data["ids"]

        existing_ids = McpTool.objects.filter(
            id__in=entity_ids, org_id=self.get_active_org_id()
        ).values_list("id", flat=True)
        if len(existing_ids) != len(entity_ids):
            return Response(
                {"message": "Some entity IDs do not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return self.import_export_service.bulk_export(
            entity_ids, org_id=self.get_active_org_id()
        )

    @extend_schema(**MCP_TOOL_IMPORT_POST)
    @action(detail=False, methods=["post"], url_path="import")
    def import_entity(self, request):
        file_serializer = ImportRequestSerializer(data=request.data)
        file_serializer.is_valid(raise_exception=True)
        vd = file_serializer.validated_data
        data = self.import_export_service.import_entity(
            vd["file"],
            user=request.user,
            settings=ImportSettings(import_labels=vd["import_labels"]),
            org_id=self.get_active_org_id(),
        )
        return Response(data, status=status.HTTP_200_OK)


class GraphOrganizationViewSet(
    OrgScopedChildViewSetMixin, viewsets.ReadOnlyModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = GraphOrganization.objects.all()
    serializer_class = GraphOrganizationSerializer


# TODO refactor to use user_variable for persistent variables
class GraphOrganizationUserViewSet(
    OrgScopedChildViewSetMixin, viewsets.ReadOnlyModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = GraphOrganizationUser.objects.all()
    serializer_class = GraphOrganizationUserSerializer


@extend_schema_view(
    create=extend_schema(**WEBHOOK_TRIGGER_NODE_CREATE),
    update=extend_schema(**WEBHOOK_TRIGGER_NODE_UPDATE),
    partial_update=extend_schema(**WEBHOOK_TRIGGER_NODE_PARTIAL_UPDATE),
)
class WebhookTriggerNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = WebhookTriggerNode.objects.select_related(
        "webhook_trigger__ngrok", "webhook_trigger__localhost"
    )
    serializer_class = WebhookTriggerNodeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["graph", "node_name", "webhook_trigger__path"]

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return WebhookTriggerNodeReadSerializer
        return WebhookTriggerNodeSerializer

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


class WebhookTriggerViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.LLM_CONFIGS
    rbac_action_map = {**DEFAULT_ACTION_MAP}
    queryset = WebhookTrigger.objects.select_related("ngrok", "localhost")
    serializer_class = WebhookTriggerNestedSerializer
    filter_backends = [DjangoFilterBackend]

    def _wait_for_tunnel_url(self, trigger):
        service = WebhookTriggerService()
        if trigger.provider_type == ProviderType.NGROK:
            service.wait_for_tunnel_url(trigger)
        elif trigger.provider_type == ProviderType.LOCALHOST:
            service.wait_for_localhost_tunnel_url(trigger)

    def perform_create(self, serializer):
        trigger = serializer.save()
        self._wait_for_tunnel_url(trigger)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        new_provider = request.data.get("provider_type", instance.provider_type)
        if new_provider in LOCAL_ONLY_PROVIDERS and instance.twilio_channels.exists():
            return Response(
                {
                    "provider_type": (
                        "Cannot switch to a local-only provider while this trigger "
                        "is linked to a Twilio channel."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        trigger = serializer.save()
        self._wait_for_tunnel_url(trigger)


class TelegramTriggerNodeViewSet(
    OrgScopedChildViewSetMixin,
    IdempotentNodeCreateMixin,
    ContentHashPreconditionMixin,
    ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    org_filter_path = "graph__org_id"
    queryset = TelegramTriggerNode.objects.select_related(
        "webhook_trigger__ngrok", "webhook_trigger__localhost"
    ).prefetch_related("fields")
    serializer_class = TelegramTriggerNodeSerializer

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return TelegramTriggerNodeReadSerializer
        return TelegramTriggerNodeSerializer


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


class BaseLabelViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    """Shared behavior for the two independent label trees — Flow labels
    (`LabelViewSet`) and Tool labels (`ToolLabelViewSet`). Each tree is a
    disjoint subset of `Label` partitioned by `Label.scope`; concrete
    subclasses set `label_scope` and a `queryset` pre-filtered to it.
    """

    rbac_action_map = {**DEFAULT_ACTION_MAP}
    serializer_class = LabelSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "parent"]
    label_scope: str = None

    def perform_create(self, serializer):
        # Never trust client-supplied scope — the URL/viewset is the only
        # source of truth for which label tree a new row joins.
        serializer.save(
            org_id=self.get_active_org_id(),
            created_by=self.request.user,
            scope=self.label_scope,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        labels = list(queryset)

        # Build paths in memory (one extra lightweight query) to avoid N+1
        # and to correctly resolve parents that may be filtered out. Scoped to
        # the active org and this tree's scope (the label tree never crosses
        # orgs or Flow/Tool scopes).
        id_to_row = {
            row["id"]: row
            for row in Label.objects.filter(
                org_id=self.get_active_org_id(), scope=self.label_scope
            ).values("id", "parent_id", "name")
        }

        def full_path_key(label):
            parts = []
            visited = set()
            current_id = label.id
            while current_id is not None:
                if current_id in visited:
                    # Stored cycle (self-parent or parent loop) — stop
                    # walking rather than looping forever.
                    break
                visited.add(current_id)
                row = id_to_row.get(current_id)
                if row is None:
                    break
                parts.append(row["name"])
                current_id = row["parent_id"]
            return "/".join(reversed(parts))

        full_paths = {label.id: full_path_key(label) for label in labels}
        labels.sort(key=lambda label: natural_sort_key(full_paths[label.id]))

        context = self.get_serializer_context()
        context["full_paths"] = full_paths

        page = self.paginate_queryset(labels)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        return Response(self.get_serializer(labels, many=True, context=context).data)


class LabelViewSet(BaseLabelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.FLOWS
    label_scope = Label.Scope.FLOW
    queryset = Label.objects.filter(scope=Label.Scope.FLOW)


class ToolLabelViewSet(BaseLabelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.TOOLS
    label_scope = Label.Scope.TOOL
    queryset = Label.objects.filter(scope=Label.Scope.TOOL)


class SecretViewSet(
    OrgScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Create / read / delete only — a Secret's name and value are immutable."""

    permission_classes = [IsAuthenticated, DenyApiKeyAuth, HasOrgPermission]
    rbac_resource_type = ResourceType.SECRETS
    rbac_action_map = {**DEFAULT_ACTION_MAP, "usage": Permission.READ}
    queryset = Secret.objects.all()
    serializer_class = SecretSerializer

    @extend_schema(**SECRET_USAGE_GET)
    @action(detail=True, methods=["get"], url_path="usage")
    def usage(self, request, pk=None):
        """Where this secret is referenced, for the deletion-safety dialog."""
        secret = self.get_object()
        return Response(secret_usage_service.summary(secret=secret))


class TwilioConfigureWebhookView(generics.GenericAPIView):
    """Set the VoiceUrl on a Twilio phone number to the configured voice stream URL.

    Credentials and the target channel are org-owned (RealtimeChannel is an
    OrgScopedModel) — org isolation is enforced in two
    layers here: `HasOrgPermission` checks that the caller's role has
    VOICE:UPDATE permission in their active org (a generic role-bit check,
    with no knowledge of this specific channel), and the manual
    `channel.org_id != active_org_id` check below verifies that the
    *specific* channel resolved by `channel_token` actually belongs to the
    caller's active org. The manual check is not a superadmin gate and must
    stay: a channel belonging to another org (or no channel at all) is
    rejected exactly like a missing token, via the same 404 "Channel not
    found" response, so existence never leaks.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.VOICE
    # Plain GenericAPIView (not router-registered), so DRF never populates
    # view.action — HasOrgPermission needs it declared explicitly. This is a
    # POST-only endpoint that mutates the Twilio webhook config of an
    # existing channel, so it maps to "update" (Permission.UPDATE) in
    # DEFAULT_ACTION_MAP, not "create" (no new resource is created).
    action = "update"

    @extend_schema(**TWILIO_CONFIGURE_WEBHOOK_POST)
    def post(self, request):
        phone_sid = request.data.get("phone_sid")
        channel_token = request.data.get("channel_token")

        try:
            webhook_url = TwilioService().configure_webhook(
                phone_sid=phone_sid,
                channel_token=channel_token,
                org_id=resolve_active_org_id(request),
            )
        except TwilioServiceError as e:
            return Response({"error": e.message}, status=e.status_code)

        return Response({"webhook_url": webhook_url})
