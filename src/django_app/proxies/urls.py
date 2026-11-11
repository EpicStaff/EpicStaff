from rest_framework.routers import DefaultRouter

from proxies.sandbox.views import (
    SandboxCustomLibraryBindingViewSet,
    SandboxVenvBindingViewSet,
    SandboxWheelViewSet,
)

router = DefaultRouter()
router.register(r"venvs", SandboxVenvBindingViewSet, basename="venv")
router.register(r"custom-libraries", SandboxCustomLibraryBindingViewSet, basename="custom-library")
router.register(
    r"custom-libraries/(?P<library_pk>[0-9]+)/wheels",
    SandboxWheelViewSet,
    basename="custom-library-wheel",
)

urlpatterns = router.urls
