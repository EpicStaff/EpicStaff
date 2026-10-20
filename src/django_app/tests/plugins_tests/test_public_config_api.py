"""Public platform config and icon of a running plugin (contract sections 3 and 6)."""

import pytest
from plugins.models import Plugin, PluginState

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import ICON_SVG, PNG_ICON, build_package, sample_files, sample_manifest

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
    Plugin.objects.filter(pk=plugin.pk).update(state=PluginState.MAINTENANCE)

    assert anonymous_client.get(f"/api/plugin-public/weather/{path}/").status_code == 404
