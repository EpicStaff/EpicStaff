from drf_spectacular.utils import extend_schema
from rbac.access.asserts import assert_org_permission
from rbac.access.gates import DenyApiKeyAuth
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedServiceViewSetMixin
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.models import Graph, UserGraphViewSettings
from tables.serializers.graph_view_settings_serializers import GraphViewSettingsSerializer
from tables.swagger_schemas.graph_view_settings_schemas import (
    GRAPH_VIEW_SETTINGS_DELETE,
    GRAPH_VIEW_SETTINGS_GET,
    GRAPH_VIEW_SETTINGS_PUT,
)


class GraphViewSettingsView(OrgScopedServiceViewSetMixin, APIView):
    """`/api/graphs/<graph_id>/my-view-settings/`: the caller's own settings for one flow.

    READ on flows is enough for every method, writes included: the settings change only
    how the caller sees the flow, never the flow, so a viewer may keep their own. For the
    same reason a write records no user action (listed in the user-action middleware's
    FALLBACK_EXCLUDED_VIEWS) and leaves the flow's `updated_at` and last editor alone.
    The rows are deliberately not copied, exported or imported with the flow
    (`GraphCopyService`, `NODE_RELATIONS` and `DEPENDENCY_ORDER` leave them out).
    """

    permission_classes = [IsAuthenticated, DenyApiKeyAuth]

    def _get_graph(self, request, graph_id: int) -> Graph:
        assert_org_permission(
            user=request.user,
            org_id=self.get_active_org_id(),
            resource_type=ResourceType.FLOWS,
            action=Permission.READ,
        )
        return self.get_in_active_org_or_404(Graph, graph_id)

    @extend_schema(**GRAPH_VIEW_SETTINGS_GET)
    def get(self, request, graph_id: int):
        graph = self._get_graph(request, graph_id)
        settings = (
            UserGraphViewSettings.objects.filter(user=request.user, graph=graph)
            .values_list("settings", flat=True)
            .first()
        )
        return Response(GraphViewSettingsSerializer({"settings": settings or {}}).data)

    @extend_schema(**GRAPH_VIEW_SETTINGS_PUT)
    def put(self, request, graph_id: int):
        graph = self._get_graph(request, graph_id)
        serializer = GraphViewSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings = serializer.validated_data["settings"]
        UserGraphViewSettings.objects.update_or_create(
            user=request.user, graph=graph, defaults={"settings": settings}
        )
        return Response(serializer.data)

    @extend_schema(**GRAPH_VIEW_SETTINGS_DELETE)
    def delete(self, request, graph_id: int):
        graph = self._get_graph(request, graph_id)
        UserGraphViewSettings.objects.filter(user=request.user, graph=graph).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
