from django.conf import settings
from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rbac.views.auth import SwaggerTokenView
from tables.views.sse_views import RunSessionSSEViewSwagger

# The API docs, the token endpoint only their "Authorize" button uses, and the
# stub that documents the run-session event stream are served in DEBUG only;
# production exposes none of them.
api_docs_urlpatterns = [
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/auth/swagger-token/", SwaggerTokenView.as_view(), name="swagger_token"),
    path(
        "api/run-session/subscribe/<int:session_id>/swagger/",
        RunSessionSSEViewSwagger.as_view(),
        name="run-session-subscribe-swagger",
    ),
]

urlpatterns = api_docs_urlpatterns if settings.DEBUG else []
