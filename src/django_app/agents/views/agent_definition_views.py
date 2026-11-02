from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
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
from tables.serializers.serializers import BulkExportSerializer, ImportRequestSerializer
from tables.services.import_export_service import ViewSetImportExportService
from tables.services.recycle_bin.sources import RecycleBinSource
from tables.swagger_schemas.tools_schemas import (
    AGENT_DEFINITION_BULK_EXPORT_POST,
    AGENT_DEFINITION_EXPORT_GET,
    AGENT_DEFINITION_IMPORT_POST,
)
from tables.views.mixins import InspectActionMixin
from tables.views.recycle_bin_mixins import RECYCLE_BIN_ACTION_MAP, RecycleBinActionsMixin

from agents.models import AgentDefinition
from agents.serializers.agent_definition_serializers import (
    AgentDefinitionReadSerializer,
    AgentDefinitionWriteSerializer,
)


class AgentDefinitionViewSet(
    OrgScopedViewSetMixin, InspectActionMixin, RecycleBinActionsMixin, viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    rbac_action_map = {
        **DEFAULT_ACTION_MAP,
        **RECYCLE_BIN_ACTION_MAP,
        "export": Permission.EXPORT,
        "bulk_export": Permission.EXPORT,
        "import_entity": Permission.CREATE,
        "inspect_import": Permission.CREATE,
    }
    recycle_bin_resource_key = RecycleBinSource.AGENT
    queryset = AgentDefinition.objects.select_related(
        "org", "llm_config", "fcm_llm_config", "realtime_agent"
    ).prefetch_related("default_surfaces__surface", "owned_surfaces", *authorship_prefetches())
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["llm_config", "fcm_llm_config"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.import_export_service = ViewSetImportExportService(
            entity_type=EntityType.AGENT_DEFINITION,
            export_prefix="agent",
            filename_attr="name",
        )

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

    @extend_schema(**AGENT_DEFINITION_EXPORT_GET)
    @action(detail=True, methods=["get"])
    def export(self, request, pk: int):
        return self.import_export_service.export_entity(
            self.get_object(), org_id=self.get_active_org_id(), user=request.user
        )

    @extend_schema(**AGENT_DEFINITION_BULK_EXPORT_POST)
    @action(detail=False, methods=["post"], url_path="bulk-export")
    def bulk_export(self, request):
        serializer = BulkExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entity_ids = serializer.validated_data["ids"]

        existing_ids = AgentDefinition.objects.filter(
            id__in=entity_ids, org_id=self.get_active_org_id()
        ).values_list("id", flat=True)
        if len(existing_ids) != len(entity_ids):
            return Response(
                {"message": "Some entity IDs do not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return self.import_export_service.bulk_export(
            entity_ids, org_id=self.get_active_org_id(), user=request.user
        )

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
