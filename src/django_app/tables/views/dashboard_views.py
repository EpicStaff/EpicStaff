from drf_spectacular.utils import extend_schema
from rbac.access.gates import HasOrgPermission
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedResolverMixin
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tables.models import DashboardReport
from tables.serializers.dashboard_serializers import DashboardReportSerializer
from tables.swagger_schemas.dashboard_schemas import DASHBOARD_REPORT_GET


class DashboardReportView(OrgScopedResolverMixin, viewsets.ViewSet):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.DASHBOARD
    rbac_action_map = {"list": Permission.READ}

    @extend_schema(**DASHBOARD_REPORT_GET)
    def list(self, request):
        report = DashboardReport.objects.filter(org_id=self.get_active_org_id()).first()
        if report is None:
            return Response({"code": "report_not_ready"}, status=status.HTTP_404_NOT_FOUND)
        return Response(DashboardReportSerializer(report).data)
