"""SuperAdmin view of a plugin's data removals (organization removed jobs): list, retry, skip.

Deployment-wide and JWT-only. A job outlives its organization, so the list also shows the
removals of deleted organizations, by the name they had.
"""

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rbac.views.cross_org_base import CrossOrgAdminPagination
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.exceptions import PluginNotFoundError
from plugins.lifecycle.org_removed_hooks import (
    UNFINISHED_ORG_REMOVED_STATES,
    OrgRemovedHookService,
    org_removed_jobs,
)
from plugins.models import Plugin, PluginHookJob
from plugins.serializers.purge import OrgRemovedJobListQuerySerializer, OrgRemovedJobSerializer
from plugins.views.admin_plugins import ADMIN_AUTHENTICATION, ADMIN_PERMISSIONS


@extend_schema(
    parameters=[
        OpenApiParameter("state", str, enum=["open", "finished", "all"]),
        OpenApiParameter("deleted_organizations", bool),
    ]
)
class PluginOrgRemovedJobListView(generics.ListAPIView):
    """A plugin's data removals, newest first; `state=open` (the default) lists the waiting,
    running and failed ones."""

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS
    serializer_class = OrgRemovedJobSerializer
    pagination_class = CrossOrgAdminPagination

    def get_queryset(self) -> QuerySet[PluginHookJob]:
        plugin = Plugin.objects.filter(identifier=self.kwargs["identifier"]).first()
        if plugin is None:
            raise PluginNotFoundError()
        query = OrgRemovedJobListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        jobs = org_removed_jobs(plugin)
        state = query.validated_data["state"]
        if state == "open":
            jobs = jobs.filter(state__in=UNFINISHED_ORG_REMOVED_STATES)
        elif state == "finished":
            jobs = jobs.exclude(state__in=UNFINISHED_ORG_REMOVED_STATES)
        deleted = query.validated_data["deleted_organizations"]
        if deleted is not None:
            jobs = jobs.filter(organization_exists=not deleted)
        return jobs


class OrgRemovedJobActionView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS


class OrgRemovedJobRetryView(OrgRemovedJobActionView):
    @extend_schema(request=None, responses={202: OrgRemovedJobSerializer})
    def post(self, request, identifier: str, job_id: int):
        job = OrgRemovedHookService().retry(identifier, job_id, request.user)
        return Response(_job_details(job), status=status.HTTP_202_ACCEPTED)


class OrgRemovedJobSkipView(OrgRemovedJobActionView):
    @extend_schema(request=None, responses=OrgRemovedJobSerializer)
    def post(self, request, identifier: str, job_id: int):
        job = OrgRemovedHookService().skip(identifier, job_id, request.user)
        return Response(_job_details(job))


def _job_details(job: PluginHookJob) -> dict:
    """A job as the list shows it, read again after a change."""
    return OrgRemovedJobSerializer(org_removed_jobs(job.plugin).get(pk=job.pk)).data
