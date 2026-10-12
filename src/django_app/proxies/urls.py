from rest_framework.routers import DefaultRouter

from proxies.sandbox.views import SandboxVenvBindingViewSet

router = DefaultRouter()
router.register(r"venvs", SandboxVenvBindingViewSet, basename="venv")

urlpatterns = router.urls
