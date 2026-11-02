from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from rbac.governance.organization_retention import OrganizationRetentionService
from rbac.models.enums import Permission, ResourceType
from rbac.schemas.organization_retention import (
    ORGANIZATION_RETENTION_GET,
    ORGANIZATION_RETENTION_PATCH,
)
from rbac.serializers.organization_retention import OrganizationRetentionResponseSerializer
from rbac.views.cross_org_base import CrossOrgAdminViewSet


class OrganizationRetentionAdminViewSet(CrossOrgAdminViewSet):
    """GET / PATCH /api/admin/organizations/{id}/retention/.

    Gated like the organization detail endpoint: the door gate needs the ORGANIZATIONS
    bit in some organization, and the service checks it in the target one.
    """

    rbac_resource_type = ResourceType.ORGANIZATIONS
    rbac_action_map = {
        "retrieve": Permission.READ,
        "partial_update": Permission.UPDATE,
    }

    _service = OrganizationRetentionService()

    @extend_schema(**ORGANIZATION_RETENTION_GET)
    def retrieve(self, request, pk=None):
        retention = self._service.get_retention(actor=request.user, org_id=int(pk))
        return self._respond(request, retention)

    @extend_schema(**ORGANIZATION_RETENTION_PATCH)
    def partial_update(self, request, pk=None):
        retention = self._service.update_retention(
            actor=request.user, org_id=int(pk), data=request.data
        )
        return self._respond(request, retention)

    @staticmethod
    def _respond(request, retention):
        return Response(
            OrganizationRetentionResponseSerializer(retention, context={"request": request}).data
        )
