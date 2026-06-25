from __future__ import annotations

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.response import Response

from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.models.agent_models.surface_models import Surface
from tables.models.rbac_models import Organization
from tables.serializers.model_serializers.surface_serializers import (
    SurfacePatchWriteSerializer,
    SurfaceReadSerializer,
    SurfaceWriteSerializer,
)


class SurfaceViewSet(viewsets.ModelViewSet):
    queryset = Surface.objects.select_related(
        "organization",
        "owner_agent",
    ).prefetch_related(
        "python_tools__python_tool",
        "mcp_tools__mcp_tool",
        "storage_items__storage_file",
        "knowledge__collection",
        "knowledge__naive_search_config",
        "knowledge__graph_basic_search_config",
        "knowledge__graph_local_search_config",
    )

    def _get_organization(self):
        return Organization.objects.get(name=DEFAULT_ORGANIZATION_NAME)

    def get_serializer_class(self):
        if self.action in ("list", "retrieve"):
            return SurfaceReadSerializer
        if self.action == "partial_update":
            return SurfacePatchWriteSerializer
        return SurfaceWriteSerializer

    def get_queryset(self):
        return super().get_queryset().filter(organization=self._get_organization())

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["organization"] = self._get_organization()
        return context

    @extend_schema(request=SurfaceWriteSerializer, responses=SurfaceReadSerializer)
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        ctx = self.get_serializer_context()
        write_serializer = SurfaceWriteSerializer(data=request.data, context=ctx)
        write_serializer.is_valid(raise_exception=True)
        instance = write_serializer.save()
        instance.refresh_from_db()

        return Response(
            SurfaceReadSerializer(instance, context=ctx).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=SurfaceWriteSerializer, responses=SurfaceReadSerializer)
    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        ctx = self.get_serializer_context()

        write_serializer = SurfaceWriteSerializer(
            instance, data=request.data, partial=False, context=ctx
        )
        write_serializer.is_valid(raise_exception=True)
        instance = write_serializer.save()
        instance.refresh_from_db()

        return Response(
            SurfaceReadSerializer(instance, context=ctx).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=SurfacePatchWriteSerializer, responses=SurfaceReadSerializer)
    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        ctx = self.get_serializer_context()
        ctx["partial"] = True

        write_serializer = SurfacePatchWriteSerializer(
            instance, data=request.data, partial=True, context=ctx
        )
        write_serializer.is_valid(raise_exception=True)
        instance = write_serializer.save()
        instance.refresh_from_db()

        return Response(
            SurfaceReadSerializer(instance, context=ctx).data,
            status=status.HTTP_200_OK,
        )
