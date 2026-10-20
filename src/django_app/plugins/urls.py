from django.urls import path

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
from plugins.views.available_plugins import AvailablePluginsView
from plugins.views.public_config import PluginIconView, PluginPublicConfigView

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
    path("api/plugins/available/", AvailablePluginsView.as_view(), name="plugins-available"),
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
]
