"""Public platform config, icon and app menu icons of a running plugin."""

import pytest
from plugins.models import Plugin, PluginState

from tests.plugins_tests.conftest import mark_running, upload_file
from tests.plugins_tests.package_builder import (
    ICON_SVG,
    MENU_ICON_PNG,
    MENU_ICON_SVG,
    PNG_ICON,
    SAMPLE_NAVIGATION,
    build_package,
    menu_manifest,
    menu_spa,
    sample_files,
    sample_manifest,
)

MENU_ICON_URL = "/api/plugin-public/weather/icons/forecast.svg/"

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]


def test_the_config_of_a_running_plugin(anonymous_client, running_plugin):
    running_plugin()

    response = anonymous_client.get("/api/plugin-public/weather/config/")

    assert response.status_code == 200
    assert response.json() == {
        "plugin": {"identifier": "weather", "name": "Weather", "version": "0.1.0"},
        "epicstaff_origin": "http://epicstaff.localhost",
        "frame_protocol": 1,
        "api_base": "/api/",
        "login": None,
    }
    assert response["Cache-Control"] == "public, max-age=60"


def test_the_config_names_the_epicstaff_origin_with_its_port(anonymous_client, running_plugin, settings):
    settings.FRONTEND_BASE_URL = "https://epicstaff.example.com:8443"
    running_plugin()

    assert anonymous_client.get("/api/plugin-public/weather/config/").json()["epicstaff_origin"] == (
        "https://epicstaff.example.com:8443"
    )


def test_a_login_token_is_not_needed_and_a_bad_one_is_ignored(anonymous_client, running_plugin):
    running_plugin()
    anonymous_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")

    assert anonymous_client.get("/api/plugin-public/weather/config/").status_code == 200


def test_the_svg_icon_and_its_headers(anonymous_client, running_plugin):
    running_plugin()

    response = anonymous_client.get("/api/plugin-public/weather/icon/", {"v": "0.1.0"})

    assert response.status_code == 200
    assert response.content == ICON_SVG
    assert response["Content-Type"] == "image/svg+xml"
    assert response["Cache-Control"] == "public, max-age=3600"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def test_a_png_icon_is_served_as_png(anonymous_client, installation, superadmin):
    manifest = sample_manifest(icon="icon.png")
    data = build_package({**sample_files(manifest), "icon.png": PNG_ICON}, manifest=manifest)
    package = installation.upload(upload_file(data), len(data), superadmin)
    installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    response = anonymous_client.get("/api/plugin-public/weather/icon/")

    assert response.content == PNG_ICON
    assert response["Content-Type"] == "image/png"


@pytest.mark.parametrize("path", ["config", "icon"])
def test_an_unknown_plugin_is_not_found(anonymous_client, path):
    response = anonymous_client.get(f"/api/plugin-public/missing/{path}/")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


@pytest.mark.parametrize("path", ["config", "icon"])
def test_a_plugin_waiting_for_review_is_not_found(anonymous_client, installation, superadmin, path):
    data = build_package()
    installation.upload(upload_file(data), len(data), superadmin)

    response = anonymous_client.get(f"/api/plugin-public/weather/{path}/")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


@pytest.mark.parametrize("path", ["config", "icon"])
def test_a_plugin_that_stopped_running_is_not_found(anonymous_client, running_plugin, path):
    plugin = running_plugin()
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.FAILED)

    assert anonymous_client.get(f"/api/plugin-public/weather/{path}/").status_code == 404


@pytest.mark.parametrize("path", ["config", "icon"])
def test_a_plugin_stopped_for_an_upgrade_is_still_served(anonymous_client, running_plugin, path):
    plugin = running_plugin()
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.MAINTENANCE)

    assert anonymous_client.get(f"/api/plugin-public/weather/{path}/").status_code == 200


def test_a_plugin_with_a_backend_names_epicstaff_s_login_urls(anonymous_client, backend_plugin):
    mark_running(backend_plugin())

    response = anonymous_client.get("/api/plugin-public/weather/config/")

    assert response.status_code == 200
    assert response.json()["login"] == {
        "authorize_url": "http://epicstaff.localhost/api/auth/plugin-authorize/",
        "token_url": "http://epicstaff.localhost/api/auth/plugin-token/",
    }


def test_the_login_urls_are_on_epicstaff_s_origin_with_its_port(anonymous_client, backend_plugin, settings):
    settings.FRONTEND_BASE_URL = "https://epicstaff.example.com:8443"
    settings.PLUGINS_BASE_DOMAIN = "plugins.example.com"
    mark_running(backend_plugin())

    login = anonymous_client.get("/api/plugin-public/weather/config/").json()["login"]

    assert login["authorize_url"] == "https://epicstaff.example.com:8443/api/auth/plugin-authorize/"
    assert login["token_url"] == "https://epicstaff.example.com:8443/api/auth/plugin-token/"


# ---- the app menu's icons ----


ICON_HEADERS = {
    "Cache-Control": "public, max-age=3600",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
}


def _assert_not_found(response):
    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


@pytest.mark.parametrize(
    ("file_name", "content", "media_type"),
    [("forecast.svg", MENU_ICON_SVG, "image/svg+xml"), ("places.png", MENU_ICON_PNG, "image/png")],
)
def test_a_menu_icon_is_served_with_the_icon_headers(anonymous_client, running_plugin, file_name, content, media_type):
    running_plugin(spa=menu_spa())

    response = anonymous_client.get(f"/api/plugin-public/weather/icons/{file_name}/", {"v": "0.1.0"})

    assert response.status_code == 200
    assert response.content == content
    assert response["Content-Type"] == media_type
    assert {header: response[header] for header in ICON_HEADERS} == ICON_HEADERS


def test_a_menu_icon_is_one_query(anonymous_client, running_plugin, django_assert_num_queries):
    running_plugin(spa=menu_spa())

    with django_assert_num_queries(1):
        assert anonymous_client.get(MENU_ICON_URL).status_code == 200


@pytest.mark.parametrize("file_name", ["unknown.svg", "icon.svg", "..", "forecast.SVG"])
def test_a_file_the_menu_does_not_name_is_not_found(anonymous_client, running_plugin, file_name):
    running_plugin(spa=menu_spa())

    _assert_not_found(anonymous_client.get(f"/api/plugin-public/weather/icons/{file_name}/"))


def test_a_menu_icon_of_an_unknown_plugin_is_not_found(anonymous_client):
    _assert_not_found(anonymous_client.get("/api/plugin-public/missing/icons/forecast.svg/"))


def test_a_plugin_waiting_for_review_serves_no_menu_icon(anonymous_client, installation, superadmin):
    data = build_package(manifest=menu_manifest())
    installation.upload(upload_file(data), len(data), superadmin)

    _assert_not_found(anonymous_client.get(MENU_ICON_URL))


def test_only_the_current_package_s_menu_icons_are_served(anonymous_client, running_plugin, installation, superadmin):
    running_plugin(spa=menu_spa())
    redrawn = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/></svg>'
    newer = menu_manifest(
        [*SAMPLE_NAVIGATION, {"label": "Alerts", "path": "/alerts", "icon": "icons/alerts.svg"}], version="0.2.0"
    )
    data = build_package({**sample_files(newer), "icons/forecast.svg": redrawn}, manifest=newer)
    installation.upload(upload_file(data), len(data), superadmin)

    served = anonymous_client.get(MENU_ICON_URL)

    assert served.status_code == 200
    assert served.content == MENU_ICON_SVG
    _assert_not_found(anonymous_client.get("/api/plugin-public/weather/icons/alerts.svg/"))


def test_a_plugin_that_stopped_running_serves_no_menu_icon(anonymous_client, running_plugin):
    plugin = running_plugin(spa=menu_spa())
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.FAILED)

    _assert_not_found(anonymous_client.get(MENU_ICON_URL))


def test_a_plugin_stopped_for_an_upgrade_still_serves_its_menu_icons(anonymous_client, running_plugin):
    plugin = running_plugin(spa=menu_spa())
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.MAINTENANCE)

    response = anonymous_client.get(MENU_ICON_URL)

    assert response.status_code == 200
    assert response.content == MENU_ICON_SVG


def test_another_plugin_s_menu_icon_is_not_served_under_this_plugin(anonymous_client, running_plugin):
    running_plugin(spa=menu_spa())
    running_plugin(id="forecast", name="Forecast")

    _assert_not_found(anonymous_client.get("/api/plugin-public/forecast/icons/forecast.svg/"))

