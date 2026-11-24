from rest_framework.routers import SimpleRouter

from ai_models.views.catalog import ModelCatalogViewSet

router = SimpleRouter()
# Routes: providers/, models/, schemas/ (names ai-models-<action>).
router.register("", ModelCatalogViewSet, basename="ai-models")

urlpatterns = router.urls
