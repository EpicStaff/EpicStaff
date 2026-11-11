"""The app's URLconf with the DEBUG-only API docs routes mounted regardless of DEBUG.

Tests run with DEBUG off, so a test that calls a docs-only endpoint (the
Swagger token endpoint) uses `@pytest.mark.urls("tests.urls_with_api_docs")`.
"""

from django_app.urls import urlpatterns as app_urlpatterns
from django_app.yasg import api_docs_urlpatterns

urlpatterns = [*app_urlpatterns, *api_docs_urlpatterns]
