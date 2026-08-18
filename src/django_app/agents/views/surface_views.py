from __future__ import annotations

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from agents.models.surface_models import Surface
from tables.models.rbac_models import Organization
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.permission_action_map import DEFAULT_ACTION_MAP
from tables.services.rbac.permissions import HasOrgPermission
from tables.views.mixins import OrgScopedResolverMixin
from agents.serializers.surface_serializers import (
    SurfaceCombineRequestSerializer,
    SurfacePatchWriteSerializer,
    SurfaceReadSerializer,
    SurfaceWriteSerializer,
)
from agents.services.surface_combine_service import SurfaceCombineService


class SurfaceViewSet(OrgScopedResolverMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.SURFACES
    rbac_action_map = {**DEFAULT_ACTION_MAP, "combine": Permission.READ}
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
        return Organization.objects.get(id=self.get_active_org_id())

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

    @extend_schema(
        request=SurfaceCombineRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=SurfaceReadSerializer,
                description="Combined surface data merged from the requested surfaces.",
            ),
            400: OpenApiResponse(
                description="Invalid surface ids or conflicting RAG configs."
            ),
        },
    )
    @action(detail=False, methods=["post"], url_path="combine")
    def combine(self, request):
        ctx = self.get_serializer_context()
        request_serializer = SurfaceCombineRequestSerializer(
            data=request.data, context=ctx
        )
        request_serializer.is_valid(raise_exception=True)

        validated_ids = {s.pk for s in request_serializer.validated_data["surface_ids"]}
        surfaces_qs = self.get_queryset().filter(id__in=validated_ids)
        surface_dicts = [
            SurfaceReadSerializer(surface, context=ctx).data for surface in surfaces_qs
        ]

        combined = SurfaceCombineService.combine(surface_dicts)
        return Response(combined, status=status.HTTP_200_OK)
