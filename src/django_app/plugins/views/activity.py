"""Plugin activity: what plugins did in an organization, and what was done to them.

The organization endpoints are for holders of `audit: read` (Org Admins by default) in the
active organization: its events (never deployment-wide ones) and the plugins acting in it
with their declared access. The admin endpoint shows a SuperAdmin every organization's
events of one plugin and the deployment-wide ones. All are pinned to people's credentials:
a plugin's service account never reads activity.
"""

from django.db.models import F, OuterRef, Subquery
from django.db.models.functions import Lower
from rbac.access.gates import HasOrgPermission
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedResolverMixin
from rbac.views.cross_org_base import CrossOrgAdminPagination
from rest_framework import generics, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from plugins.exceptions import PluginNotFoundError
from plugins.models import (
    Plugin,
    PluginActivityEvent,
    PluginServiceAccount,
    PluginServiceAccountKey,
)
from plugins.serializers.activity import (
    AdminActivityQuerySerializer,
    OrganizationActivityQuerySerializer,
    OrganizationServiceAccountSerializer,
    PluginActivityEventSerializer,
    activity_context,
)
from plugins.views.admin_plugins import ADMIN_AUTHENTICATION, ADMIN_PERMISSIONS

NEWEST_FIRST = ("-created_at", "-pk")


class _OrganizationAuditView(OrgScopedResolverMixin):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_resource_type = ResourceType.AUDIT
    rbac_action_map = {"list": Permission.READ, "retrieve": Permission.READ}


class PluginActivityViewSet(_OrganizationAuditView, viewsets.ReadOnlyModelViewSet):
    """The active organization's plugin activity, newest first, filtered by plugin or action."""

    queryset = PluginActivityEvent.objects.all()
    serializer_class = PluginActivityEventSerializer
    pagination_class = CrossOrgAdminPagination
    lookup_url_kwarg = "event_id"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(organization_id=self.get_active_org_id())
            .order_by(*NEWEST_FIRST)
        )

    def list(self, request):
        query = OrganizationActivityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        events = self.get_queryset()
        if "plugin" in query.validated_data:
            events = events.filter(plugin_identifier=query.validated_data["plugin"])
        if "action" in query.validated_data:
            events = events.filter(action=query.validated_data["action"])
        return _paginated_events(self, events)

    def retrieve(self, request, event_id=None):
        event = self.get_object()
        return Response(
            PluginActivityEventSerializer(event, context=activity_context([event])).data
        )


class OrganizationServiceAccountViewSet(_OrganizationAuditView, viewsets.ViewSet):
    """The plugins acting in the active organization, with the access each declared."""

    def list(self, request):
        last_used = (
            PluginServiceAccountKey.objects.filter(
                service_account=OuterRef("pk"), last_used_at__isnull=False
            )
            .order_by(F("last_used_at").desc())
            .values("last_used_at")[:1]
        )
        accounts = (
            PluginServiceAccount.objects.filter(
                grant__org_id=self.get_active_org_id(),
                grant__plugin__current_package__isnull=False,
            )
            .select_related("grant__plugin__current_package")
            .defer("grant__plugin__current_package__icon_bytes")
            .annotate(key_last_used_at=Subquery(last_used))
            .order_by(Lower("grant__plugin__name"), "grant__plugin__identifier")
        )
        return Response(OrganizationServiceAccountSerializer(accounts, many=True).data)


class PluginAdminActivityView(generics.ListAPIView):
    """Every event of one plugin, in every organization and deployment-wide, for a SuperAdmin."""

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS
    serializer_class = PluginActivityEventSerializer
    pagination_class = CrossOrgAdminPagination

    def get_queryset(self):
        identifier = self.kwargs["identifier"]
        events = PluginActivityEvent.objects.filter(plugin_identifier=identifier)
        # Events outlive their plugin, so a removed plugin's history is still found.
        if not Plugin.objects.filter(identifier=identifier).exists() and not events.exists():
            raise PluginNotFoundError()
        return events.order_by(*NEWEST_FIRST)

    def list(self, request, identifier: str):
        query = AdminActivityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        events = self.get_queryset()
        if "organization_id" in query.validated_data:
            events = events.filter(organization_id=query.validated_data["organization_id"])
        if "action" in query.validated_data:
            events = events.filter(action=query.validated_data["action"])
        return _paginated_events(self, events)


def _paginated_events(view, events) -> Response:
    page = view.paginate_queryset(events)
    return view.get_paginated_response(
        PluginActivityEventSerializer(page, many=True, context=activity_context(page)).data
    )
