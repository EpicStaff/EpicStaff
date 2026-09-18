from django.urls import include, path
from rest_framework.routers import DefaultRouter

from agents.views.agent_definition_views import AgentDefinitionViewSet
from agents.views.surface_views import SurfaceViewSet

router = DefaultRouter()
router.register(
    r"agent-definitions", AgentDefinitionViewSet, basename="agentdefinition"
)
router.register(r"surfaces", SurfaceViewSet, basename="surface")

urlpatterns = [path("", include(router.urls))]
