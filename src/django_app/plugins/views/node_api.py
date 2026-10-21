"""The node API: what the plugin node agent polls, downloads and reports.

Reached through nginx's internal listener on the plugins network. Authenticated by the node
key only (`PluginNodeAuthentication`); each node sees only its own placements and their
packages, and anything else answers 404.
"""

from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.views import APIView

from plugins.exceptions import PluginPackageNotFoundError
from plugins.models import PluginPackage
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
        placement = placements_to_run(node).filter(plugin__current_package_id=package_id).first()
        if placement is None:
            raise PluginPackageNotFoundError()
        return placement.plugin.current_package


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
