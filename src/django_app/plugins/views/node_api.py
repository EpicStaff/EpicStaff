"""The node API: what the plugin node agent polls, downloads and reports.

Reached through nginx's internal listener on the plugins network. Authenticated by the node
key only (`PluginNodeAuthentication`); each node sees only its own placements and their
packages, and anything else answers 404.
"""

from functools import partial

from django.db.models import Exists, OuterRef
from django.http import FileResponse, HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.views import APIView

from plugins.exceptions import PluginPackageNotFoundError
from plugins.lifecycle.hook_job_service import HookJobService, parse_hook_result
from plugins.lifecycle.upgrade_service import PluginUpgradeService, parse_upgrade_advance
from plugins.models import Plugin, PluginPackage, PluginUpgrade
from plugins.models.upgrade import OPEN_UPGRADE_STAGES
from plugins.nodes.desired_state_builder import DesiredStateBuilder, placements_to_run
from plugins.nodes.node_authentication import IsPluginNode, PluginNodeAuthentication
from plugins.nodes.node_report_service import NodeReportService, parse_node_report
from plugins.nodes.runtime_credentials_service import RuntimeCredentialsService
from plugins.packages.package_store import PackageFileMissingError, get_package_store

JSON = "application/json"


class PluginNodeView(APIView):
    authentication_classes = [PluginNodeAuthentication]
    permission_classes = [IsPluginNode]


class DesiredStateView(PluginNodeView):
    def get(self, request):
        desired = DesiredStateBuilder().build(request.auth)
        etag = f'"{desired.revision}"'
        if request.META.get("HTTP_IF_NONE_MATCH", "").strip() == etag:
            response = HttpResponse(status=status.HTTP_304_NOT_MODIFIED)
        else:
            response = HttpResponse(desired.model_dump_json(), content_type=JSON)
        response["ETag"] = etag
        return response


class NodePackageView(PluginNodeView):
    def get(self, request, package_id: int):
        package = self._package_of_node(request.auth, package_id)
        try:
            stream, size = get_package_store().open(package.storage_key)
        except PackageFileMissingError:
            raise PluginPackageNotFoundError() from None
        # Streamed from the bucket in chunks, never held whole; FileResponse closes the
        # stream once the body has been sent.
        response = FileResponse(stream, content_type="application/octet-stream")
        response["Content-Length"] = str(size)
        response["X-Package-Sha256"] = package.sha256
        return response

    @staticmethod
    def _package_of_node(node, package_id: int) -> PluginPackage:
        """The package if it is the current package or an open upgrade's target of a plugin
        placed on `node`; any other answers 404."""
        plugins = placements_to_run(node).values("plugin_id")
        package = (
            PluginPackage.objects.filter(pk=package_id)
            .filter(
                Exists(Plugin.objects.filter(pk__in=plugins, current_package_id=OuterRef("pk")))
                | Exists(
                    PluginUpgrade.objects.filter(
                        plugin_id__in=plugins,
                        to_package_id=OuterRef("pk"),
                        stage__in=OPEN_UPGRADE_STAGES,
                    )
                )
            )
            .only("pk", "storage_key", "sha256")
            .first()
        )
        if package is None:
            raise PluginPackageNotFoundError()
        return package


class RuntimeCredentialsView(PluginNodeView):
    def post(self, request, placement_id: int):
        credentials = RuntimeCredentialsService().credentials_for(request.auth, placement_id)
        response = HttpResponse(credentials.model_dump_json(), content_type=JSON)
        # The body holds the plugin's secret settings.
        response["Cache-Control"] = "no-store"
        return response


class NodeReportView(PluginNodeView):
    def post(self, request):
        NodeReportService().record(request.auth, parse_node_report(request.body))
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)


class HookJobClaimView(PluginNodeView):
    def post(self, request, job_id: int):
        invocation = HookJobService().claim(request.auth, job_id)
        response = HttpResponse(invocation.model_dump_json(), content_type=JSON)
        # The body holds a signed hook assertion.
        response["Cache-Control"] = "no-store"
        return response


class HookJobResultView(PluginNodeView):
    def post(self, request, job_id: int):
        HookJobService().record_result(request.auth, job_id, parse_hook_result(request.body))
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)


class UpgradeAdvanceView(PluginNodeView):
    """The node asking to take an upgrade of one of its placements to its next stage."""

    @extend_schema(request=None, responses={204: None})
    def post(self, request, upgrade_id: int):
        # The service reads the body once it has found the upgrade: 404, then 409, then 400.
        PluginUpgradeService().advance(
            request.auth, upgrade_id, partial(parse_upgrade_advance, request.body)
        )
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)
