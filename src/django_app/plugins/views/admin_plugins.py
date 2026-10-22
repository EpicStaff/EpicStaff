"""SuperAdmin plugin management: upload, review, approve or reject, list, grant, delete.

Deployment-wide and JWT-only. The org is data here (a grant's organization comes from the
body), never the `X-Organization-Id` header, which the frontend does not send on /admin/.
"""

from django.db.models.functions import Lower
from drf_spectacular.utils import extend_schema
from rbac.access.gates import DenyApiKeyAuth, IsSuperadmin
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rbac.views.cross_org_base import CrossOrgAdminPagination
from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.exceptions import PackageTooLargeError, PluginNotFoundError, PluginPackageNotFoundError
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.lifecycle.hook_job_service import HookJobService
from plugins.lifecycle.installation_service import PluginInstallationService, max_package_bytes
from plugins.lifecycle.plugin_purge_service import PluginPurgeService
from plugins.models import Plugin, PluginGrant, PluginPackage
from plugins.ownership.owned_resource_summary import with_owned_resource_counts
from plugins.serializers.admin import (
    GrantCreateSerializer,
    PackageReviewSerializer,
    PackageUploadSerializer,
    PluginDetailSerializer,
    PluginGrantSerializer,
    PluginSummarySerializer,
)
from plugins.serializers.purge import VerificationPhraseSerializer
from plugins.serializers.upgrade import UpgradeApprovalSerializer

ADMIN_PERMISSIONS = [IsAuthenticated, IsSuperadmin, DenyApiKeyAuth]
# Pinned rather than inherited from the defaults, so no plugin credential is ever read here.
ADMIN_AUTHENTICATION = [JwtAuthentication, ApiKeyAuthentication]
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

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


class PluginPackageUploadView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS
    parser_classes = [MultiPartParser]

    @extend_schema(request=PackageUploadSerializer, responses={201: PackageReviewSerializer})
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
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(responses=PackageReviewSerializer)
    def get(self, request, package_id: int):
        return Response(PackageReviewSerializer(_package_for_review(package_id)).data)


class PluginPackageApproveView(APIView):
    """Approve a pending package: install the plugin, or start its upgrade.

    A first install answers 200. An upgrade answers 202 while it runs, or 200 when it
    completed at once (neither version has a backend).
    """

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(
        request=UpgradeApprovalSerializer,
        responses={200: PluginDetailSerializer, 202: PluginDetailSerializer},
    )
    def post(self, request, package_id: int):
        serializer = UpgradeApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = serializer.validated_data
        plugin = PluginInstallationService().approve(
            package_id,
            request.user,
            untrusted_acknowledged=body["untrusted_acknowledged"],
            access_growth_acknowledged=body["access_growth_acknowledged"],
            reviewed_against_package_id=body["reviewed_against_package_id"],
            settings=body["settings"],
        )
        details = PluginDetailSerializer(plugin).data
        upgrading = details["open_upgrade"] is not None
        return Response(
            details, status=status.HTTP_202_ACCEPTED if upgrading else status.HTTP_200_OK
        )


class PluginPackageRejectView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    def post(self, request, package_id: int):
        PluginInstallationService().reject(package_id, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PluginListView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    def get(self, request):
        plugins = Plugin.objects.with_summary().order_by(Lower("name"), "identifier")
        return Response(PluginSummarySerializer(plugins, many=True).data)


class PluginDetailView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(responses=PluginDetailSerializer)
    def get(self, request, identifier: str):
        return Response(plugin_details(identifier))

    @extend_schema(request=VerificationPhraseSerializer, responses={202: PluginDetailSerializer})
    def delete(self, request, identifier: str):
        """Delete the plugin for good: every organization's data, its database and its files.
        Irreversible: the body carries the phrase the purge preview shows."""
        PluginPurgeService().request(identifier, request.data, request.user)
        return Response(plugin_details(identifier), status=status.HTTP_202_ACCEPTED)


class PluginGrantListView(generics.ListAPIView):
    """Every organization's grant of one plugin; the SuperAdmin sees them all by design."""

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS
    serializer_class = PluginGrantSerializer
    pagination_class = CrossOrgAdminPagination

    def get_queryset(self):
        identifier = self.kwargs["identifier"]
        if not Plugin.objects.filter(identifier=identifier).exists():
            raise PluginNotFoundError()
        return (
            PluginGrant.objects.filter(plugin__identifier=identifier)
            .with_admin_details()
            .order_by(Lower("org__name"), "id")
        )

    def paginate_queryset(self, queryset):
        return with_owned_resource_counts(super().paginate_queryset(queryset))

    def post(self, request, identifier: str):
        serializer = GrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant = PluginGrantService().grant(
            identifier, serializer.validated_data["organization_id"], request.user
        )
        return Response(grant_details(grant.pk), status=status.HTTP_201_CREATED)


class PluginGrantRetryHookView(APIView):
    """Run a grant's failed install or upgrade hook again: the grant is `granting` or
    `upgrading` until the node reports."""

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(request=None, responses={202: PluginGrantSerializer})
    def post(self, request, identifier: str, grant_id: int):
        grant = HookJobService().retry(identifier, grant_id, request.user)
        return Response(grant_details(grant.pk), status=status.HTTP_202_ACCEPTED)


def plugin_details(identifier: str) -> dict:
    """A plugin as its detail page shows it, read again after a change."""
    return PluginDetailSerializer(_plugin_or_404(identifier)).data


def grant_details(grant_id: int) -> dict:
    """A grant as the SuperAdmin's grant list shows it, read again after a change."""
    [grant] = with_owned_resource_counts(
        [PluginGrant.objects.with_admin_details().get(pk=grant_id)]
    )
    return PluginGrantSerializer(grant).data
