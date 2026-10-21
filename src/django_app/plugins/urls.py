from django.urls import path

from plugins.gateway.gateway_check_view import gateway_check
from plugins.views.admin_backend import (
    PluginLimitsView,
    PluginRestartView,
    PluginRuntimeView,
    PluginSettingsView,
)
from plugins.views.admin_plugins import (
    PluginDetailView,
    PluginGrantListView,
    PluginListView,
    PluginPackageApproveView,
    PluginPackageRejectView,
    PluginPackageReviewView,
    PluginPackageUploadView,
    PluginUploadPermissionView,
)
from plugins.views.admin_role_permissions import PluginRolePermissionViewSet
from plugins.views.available_plugins import AvailablePluginsView
from plugins.views.node_api import (
    DesiredStateView,
    NodePackageView,
    NodeReportView,
    RuntimeCredentialsView,
)
from plugins.views.public_config import PluginIconView, PluginJwksView, PluginPublicConfigView

role_plugin_rows = PluginRolePermissionViewSet.as_view({"get": "rows"})
role_plugin_permissions = PluginRolePermissionViewSet.as_view({"get": "retrieve", "put": "update"})

urlpatterns = [
    path("api/admin/plugins/", PluginListView.as_view(), name="admin-plugins"),
    path(
        "api/admin/plugins/packages/",
        PluginPackageUploadView.as_view(),
        name="admin-plugin-packages",
    ),
    path(
        "api/admin/plugins/packages/upload-permission/",
        PluginUploadPermissionView.as_view(),
        name="admin-plugin-package-upload-permission",
    ),
    path(
        "api/admin/plugins/packages/<int:package_id>/review/",
        PluginPackageReviewView.as_view(),
        name="admin-plugin-package-review",
    ),
    path(
        "api/admin/plugins/packages/<int:package_id>/approve/",
        PluginPackageApproveView.as_view(),
        name="admin-plugin-package-approve",
    ),
    path(
        "api/admin/plugins/packages/<int:package_id>/reject/",
        PluginPackageRejectView.as_view(),
        name="admin-plugin-package-reject",
    ),
    path(
        "api/admin/plugins/<str:identifier>/",
        PluginDetailView.as_view(),
        name="admin-plugin-detail",
    ),
    path(
        "api/admin/plugins/<str:identifier>/grants/",
        PluginGrantListView.as_view(),
        name="admin-plugin-grants",
    ),
    path(
        "api/admin/plugins/<str:identifier>/settings/",
        PluginSettingsView.as_view(),
        name="admin-plugin-settings",
    ),
    path(
        "api/admin/plugins/<str:identifier>/limits/",
        PluginLimitsView.as_view(),
        name="admin-plugin-limits",
    ),
    path(
        "api/admin/plugins/<str:identifier>/runtime/",
        PluginRuntimeView.as_view(),
        name="admin-plugin-runtime",
    ),
    path(
        "api/admin/plugins/<str:identifier>/restart/",
        PluginRestartView.as_view(),
        name="admin-plugin-restart",
    ),
    path(
        "api/admin/plugin-role-permissions/rows/",
        role_plugin_rows,
        name="admin-plugin-role-permission-rows",
    ),
    path(
        "api/admin/plugin-role-permissions/<int:role_id>/",
        role_plugin_permissions,
        name="admin-plugin-role-permissions",
    ),
    path("api/plugins/available/", AvailablePluginsView.as_view(), name="plugins-available"),
    path("api/plugin-public/jwks/", PluginJwksView.as_view(), name="plugin-public-jwks"),
    path(
        "api/plugin-public/<str:identifier>/config/",
        PluginPublicConfigView.as_view(),
        name="plugin-public-config",
    ),
    path(
        "api/plugin-public/<str:identifier>/icon/",
        PluginIconView.as_view(),
        name="plugin-public-icon",
    ),
    path("api/plugin-gateway/check/", gateway_check, name="plugin-gateway-check"),
    path(
        "api/plugin-nodes/self/desired-state/",
        DesiredStateView.as_view(),
        name="plugin-node-desired-state",
    ),
    path(
        "api/plugin-nodes/self/packages/<int:package_id>/",
        NodePackageView.as_view(),
        name="plugin-node-package",
    ),
    path(
        "api/plugin-nodes/self/placements/<int:placement_id>/runtime-credentials/",
        RuntimeCredentialsView.as_view(),
        name="plugin-node-runtime-credentials",
    ),
    path("api/plugin-nodes/self/reports/", NodeReportView.as_view(), name="plugin-node-reports"),
]
