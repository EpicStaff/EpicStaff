from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rbac.access.gates import HasOrgPermission
from rbac.authorship import authorship_prefetches
from rbac.models.enums import ResourceType
from rbac.scoping.mixins import OrgScopedViewSetMixin
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from agents.models import AgentDefinition
from agents.serializers.agent_definition_serializers import (
    AgentDefinitionReadSerializer,
    AgentDefinitionWriteSerializer,
)


class AgentDefinitionViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AGENTS
    queryset = AgentDefinition.objects.select_related(
        "org", "llm_config", "fcm_llm_config", "realtime_agent"
    ).prefetch_related("default_surfaces__surface", "owned_surfaces", *authorship_prefetches())
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["llm_config", "fcm_llm_config"]

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
