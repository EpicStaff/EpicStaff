"""SuperAdmin plugin management: upload, review, approve or reject, list, grant.

Deployment-wide and JWT-only. The org is data here (a grant's organization comes from the
body), never the `X-Organization-Id` header, which the frontend does not send on /admin/.
"""

from django.db.models.functions import Lower
from rbac.access.gates import DenyApiKeyAuth, IsSuperadmin
from rbac.views.cross_org_base import CrossOrgAdminPagination
from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.exceptions import PackageTooLargeError, PluginNotFoundError, PluginPackageNotFoundError
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.installation_service import PluginInstallationService, max_package_bytes
from plugins.models import Plugin, PluginGrant, PluginPackage
from plugins.serializers.admin import (
    GrantCreateSerializer,
    PackageApprovalSerializer,
    PackageReviewSerializer,
    PackageUploadSerializer,
    PluginDetailSerializer,
    PluginGrantSerializer,
    PluginSummarySerializer,
)

ADMIN_PERMISSIONS = [IsAuthenticated, IsSuperadmin, DenyApiKeyAuth]
# Room for the multipart boundaries and headers around the package in the request body.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


def _plugin_or_404(identifier: str) -> Plugin:
    plugin = Plugin.objects.with_summary().filter(identifier=identifier).first()
    if plugin is None:
        raise PluginNotFoundError()
    return plugin


def _package_for_review(package_id: int) -> PluginPackage:
    package = (
        PluginPackage.objects.select_related("plugin", "uploaded_by", "approved_by")
        .filter(pk=package_id)
        .first()
    )
    if package is None:
        raise PluginPackageNotFoundError()
    return package


class PluginUploadPermissionView(APIView):
    """Answers nginx's `auth_request` for the package upload route, before the body is read.

    The ASGI server spools a request's whole body before any view runs, so the upload view's
    own gate comes too late to stop a stranger from filling the disk. nginx therefore asks
    here first, with no body, and reads the upload only after a 204. Same gate as the upload.
    nginx answers 404 to this path from outside; it is reached only through its internal
    location.
    """

    permission_classes = ADMIN_PERMISSIONS

    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


class PluginPackageUploadView(APIView):
    permission_classes = ADMIN_PERMISSIONS
    parser_classes = [MultiPartParser]

    def post(self, request):
        # The body is already spooled to a temporary file when this runs. Behind nginx only a
        # SuperAdmin gets this far (PluginUploadPermissionView, asked before the body is read),
        # and nginx caps the body; this check only spares parsing an oversized body again.
        content_length = request.META.get("CONTENT_LENGTH")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > (max_package_bytes() + MULTIPART_OVERHEAD_BYTES)
        ):
            raise PackageTooLargeError()
        serializer = PackageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        package = PluginInstallationService().upload(uploaded, uploaded.size, request.user)
        return Response(
            PackageReviewSerializer(_package_for_review(package.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class PluginPackageReviewView(APIView):
    permission_classes = ADMIN_PERMISSIONS

    def get(self, request, package_id: int):
        return Response(PackageReviewSerializer(_package_for_review(package_id)).data)


class PluginPackageApproveView(APIView):
    permission_classes = ADMIN_PERMISSIONS

    def post(self, request, package_id: int):
        serializer = PackageApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plugin = PluginInstallationService().approve(
            package_id,
            request.user,
            untrusted_acknowledged=serializer.validated_data["untrusted_acknowledged"],
        )
        return Response(PluginDetailSerializer(plugin).data)


class PluginPackageRejectView(APIView):
    permission_classes = ADMIN_PERMISSIONS

    def post(self, request, package_id: int):
        PluginInstallationService().reject(package_id, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PluginListView(APIView):
    permission_classes = ADMIN_PERMISSIONS

    def get(self, request):
        plugins = Plugin.objects.with_summary().order_by(Lower("name"), "identifier")
        return Response(PluginSummarySerializer(plugins, many=True).data)


class PluginDetailView(APIView):
    permission_classes = ADMIN_PERMISSIONS

    def get(self, request, identifier: str):
        return Response(PluginDetailSerializer(_plugin_or_404(identifier)).data)


class PluginGrantListView(generics.ListAPIView):
    """Every organization's grant of one plugin; the SuperAdmin sees them all by design."""

    permission_classes = ADMIN_PERMISSIONS
    serializer_class = PluginGrantSerializer
    pagination_class = CrossOrgAdminPagination

    def get_queryset(self):
        identifier = self.kwargs["identifier"]
        if not Plugin.objects.filter(identifier=identifier).exists():
            raise PluginNotFoundError()
        return (
            PluginGrant.objects.filter(plugin__identifier=identifier)
            .select_related("plugin", "org", "created_by")
            .order_by(Lower("org__name"), "id")
        )

    def post(self, request, identifier: str):
        serializer = GrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant = PluginGrantService().grant(
            identifier, serializer.validated_data["organization_id"], request.user
        )
        return Response(PluginGrantSerializer(grant).data, status=status.HTTP_201_CREATED)
