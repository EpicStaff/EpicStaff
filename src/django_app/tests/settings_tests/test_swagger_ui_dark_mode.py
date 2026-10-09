import pytest
from django.contrib.staticfiles import finders
from django.test import RequestFactory
from drf_spectacular.views import SpectacularSwaggerView

# Same reason as test_api_docs_toggle.py: nothing here touches the database, but the
# session-scoped autouse flush in tests/conftest.py needs proper test-database setup.
pytestmark = pytest.mark.django_db

DARK_THEME_STYLESHEET = "drf_spectacular/swagger_dark.css"


def _render_swagger_page() -> str:
    # An explicit schema url skips reverse("schema"), which only exists when DEBUG is on.
    view = SpectacularSwaggerView.as_view(url="/api/schema/")
    response = view(RequestFactory().get("/swagger/"))
    response.render()
    return response.content.decode()


def test_swagger_page_toggles_the_built_in_dark_theme_from_the_api_title():
    page = _render_swagger_page()

    assert 'root.classList.toggle("dark-mode")' in page
    assert 'event.target.closest(".swagger-ui .info .title")' in page


def test_swagger_page_only_turns_dark_mode_on_when_the_viewer_chose_it():
    page = _render_swagger_page()

    assert 'document.documentElement.classList.add("dark-mode")' not in page
    assert 'localStorage.getItem(storageKey) === "on"' in page


def test_swagger_page_links_the_dark_stylesheet_after_the_swagger_ui_stylesheet():
    page = _render_swagger_page()

    swagger_ui_stylesheet_position = page.index("/swagger-ui.css")
    dark_stylesheet_position = page.index(f"/static/{DARK_THEME_STYLESHEET}")
    assert swagger_ui_stylesheet_position < dark_stylesheet_position


def test_swagger_page_keeps_the_drf_spectacular_page_body():
    page = _render_swagger_page()

    assert '<div id="swagger-ui"></div>' in page
    assert "SwaggerUIBundle({" in page


def test_dark_stylesheet_is_found_by_the_static_finders():
    assert finders.find(DARK_THEME_STYLESHEET) is not None
