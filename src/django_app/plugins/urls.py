from django.urls import include, path
from rest_framework.routers import SimpleRouter

from plugins.asset_views import plugin_ui_asset
from plugins.views import PluginViewSet

# SimpleRouter: tables.urls already serves the API root view under /api/.
router = SimpleRouter()
router.register(r"plugins", PluginViewSet, basename="plugins")

urlpatterns = [
    path("", include(router.urls)),
    path("plugin-ui/<str:token>/<path:asset_path>", plugin_ui_asset, name="plugin-ui-asset"),
]
