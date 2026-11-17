from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rbac.access.action_map import DEFAULT_ACTION_MAP
from rbac.access.gates import HasOrgPermission
from rbac.authorship import authorship_prefetches
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedViewSetMixin
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tables.import_export.enums import EntityType
from tables.import_export.services.import_service import ImportSettings
from tables.models import TransferJob
from tables.serializers.serializers import ImportRequestSerializer
from tables.serializers.transfer_job_serializers import KnowledgeExportJobCreateSerializer
from tables.services.import_export_service import ViewSetImportExportService
from tables.services.recycle_bin.sources import RecycleBinSource
from tables.services.transfer_jobs.export_definitions import export_definition
from tables.swagger_schemas.tools_schemas import (
    AGENT_DEFINITION_COPY_POST,
    AGENT_DEFINITION_IMPORT_POST,
)
from tables.views.mixins import CopyActionMixin, ExportJobActionMixin, InspectActionMixin
from tables.views.recycle_bin_mixins import RECYCLE_BIN_ACTION_MAP, RecycleBinActionsMixin

from agents.models import AgentDefinition
from agents.serializers.agent_definition_serializers import (
    AgentDefinitionCopyRequestSerializer,
    AgentDefinitionReadSerializer,
    AgentDefinitionWriteSerializer,
)
from agents.services.agent_definition_copy_service import AgentDefinitionCopyService


@extend_schema_view(
    copy=extend_schema(**AGENT_DEFINITION_COPY_POST),
    export_jobs=extend_schema(request=KnowledgeExportJobCreateSerializer),
)
class AgentDefinitionViewSet(
    OrgScopedViewSetMixin,
    CopyActionMixin,
    ExportJobActionMixin,
    InspectActionMixin,
    RecycleBinActionsMixin,
    viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        **RECYCLE_BIN_ACTION_MAP,
        "export_jobs": Permission.EXPORT,
        "import_entity": Permission.CREATE,
        "inspect_import": Permission.CREATE,
        # Copying an agent that owns surfaces also needs surfaces CREATE, checked
        # by AgentDefinitionCopyService inside the copy's transaction.
        "copy": Permission.CREATE,
    }
    recycle_bin_resource_key = RecycleBinSource.AGENT
    copy_service_class = AgentDefinitionCopyService
    copy_serializer_class = AgentDefinitionReadSerializer
    export_job_definition = export_definition(TransferJob.MainEntity.AGENT_DEFINITION)
    export_job_request_serializer_class = KnowledgeExportJobCreateSerializer
    queryset = AgentDefinition.objects.select_related(
        "org", "llm_config", "fallback_llm_config", "fcm_llm_config", "realtime_agent"
    ).prefetch_related("default_surfaces__surface", "owned_surfaces", *authorship_prefetches())
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["llm_config", "fallback_llm_config", "fcm_llm_config"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(EntityType.AGENT_DEFINITION)

    def check_copy_allowed(self, request, instance) -> None:
        # CopyActionMixin passes the raw `name` on; refuse a malformed body here,
        # after the org-scoped 404 and before anything is written.
        AgentDefinitionCopyRequestSerializer(data=request.data).is_valid(raise_exception=True)

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return AgentDefinitionReadSerializer
        return AgentDefinitionWriteSerializer

    @extend_schema(request=AgentDefinitionWriteSerializer, responses=AgentDefinitionReadSerializer)
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        write_serializer = self.get_serializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        self.perform_create(write_serializer)

        read_serializer = AgentDefinitionReadSerializer(
            write_serializer.instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(request=AgentDefinitionWriteSerializer, responses=AgentDefinitionReadSerializer)
    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        write_serializer = self.get_serializer(instance, data=request.data, partial=False)
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        instance.refresh_from_db()
        read_serializer = AgentDefinitionReadSerializer(
            instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=AgentDefinitionWriteSerializer, responses=AgentDefinitionReadSerializer)
    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        write_serializer = self.get_serializer(instance, data=request.data, partial=True)
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        instance.refresh_from_db()
        read_serializer = AgentDefinitionReadSerializer(
            instance, context=self.get_serializer_context()
        )
        return Response(read_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(**AGENT_DEFINITION_IMPORT_POST)
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
