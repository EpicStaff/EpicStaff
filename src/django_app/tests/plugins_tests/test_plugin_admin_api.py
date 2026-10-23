"""SuperAdmin plugin API: upload, review, approve, reject, list and detail."""

import base64
import os

import pytest
import yaml
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.renderers import OpenApiYamlRenderer
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.models import (
    Plugin,
    PluginDevelopmentTarget,
    PluginPackage,
    PluginPackageNavigationIcon,
    PluginState,
    ReviewState,
)
from rest_framework.test import APIClient

from tests.plugins_tests.conftest import reload_root_urlconf, upload_file
from tests.plugins_tests.package_builder import (
    ICON_SVG,
    INDEX_HTML,
    MENU_ICON_PNG,
    MENU_ICON_SVG,
    backend_manifest,
    build_package,
    gated_menu_manifest,
    menu_manifest,
    sample_files,
    sample_manifest,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"
PLUGINS_URL = "/api/admin/plugins/"


def _upload(client, data=None):
    return client.post(PACKAGES_URL, {"file": upload_file(data or build_package())}, format="multipart")


def _approve(client, package_id, **body):
    return client.post(f"{PACKAGES_URL}{package_id}/approve/", body, format="json")


def test_upload_returns_the_package_review(superadmin_client, superadmin_user, trusts_release_key):
    response = _upload(superadmin_client, build_package(signed_with=trusts_release_key))

    assert response.status_code == 201
    review = response.json()
    assert review["plugin_identifier"] == "weather"
    assert review["version"] == "0.1.0"
    assert review["name"] == "Weather"
    assert review["publisher"] == {"name": "EpicStaff", "url": None}
    assert review["icon_data_url"].startswith("data:image/svg+xml;base64,")
    assert review["navigation"] == []
    assert (review["trust"], review["signature"], review["review_state"]) == ("trusted", "valid", "pending")
    assert review["signer"] == {"key_name": "release", "key_id": trusts_release_key.public_key.display_id}
    assert review["uploaded_by"] == {"id": superadmin_user.id, "email": superadmin_user.email}
    assert review["approved_by"] is None and review["approved_at"] is None
    assert (review["is_upgrade"], review["current_version"], review["access_growth"]) == (False, None, None)
    assert review["contents"] == {
        "has_spa": True,
        "has_backend": False,
        "has_database": False,
        "spa_file_count": 2,
        "spa_bytes": review["contents"]["spa_bytes"],
        "wheel_count": 0,
        "migration_count": 0,
    }
    assert review["user_permissions"] == [
        {
            "action": "read",
            "label": "View",
            "description": "Open Weather and see forecasts.",
            "defaults": {"org_admin": True, "member": True, "viewer": False},
        }
    ]
    assert review["access"] == review["public_paths"] == review["outbound_hosts"] == review["settings"] == []
    assert review["limits"] is None
    assert review["hooks"] == {"install": False, "upgrade": False, "org_removed": False}
    assert review["warnings"] == []
    assert len(review["sha256"]) == 64 and review["size"] > 0


def test_a_new_identifier_creates_its_plugin_as_uploaded(superadmin_client, package_store):
    review = _upload(superadmin_client).json()

    plugin = Plugin.objects.get(identifier="weather")
    assert plugin.state == PluginState.UPLOADED
    assert plugin.current_package is None
    package = PluginPackage.objects.get(pk=review["id"])
    assert package.storage_key == f"packages/weather/0.1.0/{review['sha256']}.esplugin"
    assert package_store.objects[package.storage_key] == build_package()


def test_an_untrusted_review_carries_the_untrusted_warning(superadmin_client):
    review = _upload(superadmin_client).json()

    assert review["trust"] == "untrusted" and review["signer"] is None
    assert [warning["code"] for warning in review["warnings"]] == ["untrusted_package"]


def test_review_returns_the_same_review(superadmin_client):
    review = _upload(superadmin_client).json()

    response = superadmin_client.get(f"{PACKAGES_URL}{review['id']}/review/")

    assert response.status_code == 200
    assert response.json() == review


def test_approving_a_trusted_package_runs_the_plugin_and_publishes_its_spa(
    superadmin_client, superadmin_user, trusts_release_key, spa_root, django_capture_on_commit_callbacks
):
    review = _upload(superadmin_client, build_package(signed_with=trusts_release_key)).json()

    with django_capture_on_commit_callbacks(execute=True):
        response = _approve(superadmin_client, review["id"])

    assert response.status_code == 200
    detail = response.json()
    assert detail["state"] == "running"
    assert detail["current_version"] == "0.1.0"
    assert detail["trust"] == "trusted"
    assert detail["icon_url"] == "/api/plugin-public/weather/icon/?v=0.1.0"
    assert detail["frame_origin"] == "http://weather.plugins.epicstaff.localhost"
    assert detail["pending_package"] is None
    assert detail["grant_count"] == 0
    assert detail["current_package"]["review_state"] == "approved"
    assert detail["current_package"]["approved_by"] == {"id": superadmin_user.id, "email": superadmin_user.email}
    assert (spa_root / "weather" / "0.1.0" / "index.html").read_bytes() == INDEX_HTML
    assert os.readlink(spa_root / "weather" / "current") == "0.1.0"


def test_an_untrusted_package_needs_the_acknowledgement(superadmin_client):
    review = _upload(superadmin_client).json()

    refused = _approve(superadmin_client, review["id"])
    refused_false = _approve(superadmin_client, review["id"], untrusted_acknowledged=False)
    approved = _approve(superadmin_client, review["id"], untrusted_acknowledged=True)

    assert refused.status_code == refused_false.status_code == 400
    assert refused.json()["code"] == "untrusted_not_acknowledged"
    assert approved.status_code == 200
    assert approved.json()["state"] == "running"


def test_a_package_can_be_decided_only_once(superadmin_client):
    review = _upload(superadmin_client).json()
    _approve(superadmin_client, review["id"], untrusted_acknowledged=True)

    again = _approve(superadmin_client, review["id"], untrusted_acknowledged=True)
    rejected = superadmin_client.post(f"{PACKAGES_URL}{review['id']}/reject/")

    assert again.status_code == rejected.status_code == 409
    assert again.json()["code"] == rejected.json()["code"] == "package_not_pending"


def test_rejecting_deletes_the_package_its_file_and_a_never_approved_plugin(
    superadmin_client, package_store, django_capture_on_commit_callbacks
):
    review = _upload(superadmin_client).json()

    with django_capture_on_commit_callbacks(execute=True):
        response = superadmin_client.post(f"{PACKAGES_URL}{review['id']}/reject/")

    assert response.status_code == 204
    assert not PluginPackage.objects.exists()
    assert not Plugin.objects.exists()
    assert package_store.objects == {}


def test_a_new_upload_replaces_the_pending_package(superadmin_client, package_store, django_capture_on_commit_callbacks):
    first = _upload(superadmin_client).json()

    with django_capture_on_commit_callbacks(execute=True):
        second = _upload(superadmin_client, build_package(manifest=sample_manifest(version="0.1.1", name="Weather 2"))).json()

    assert list(PluginPackage.objects.values_list("id", flat=True)) == [second["id"]]
    assert Plugin.objects.get().name == "Weather 2"
    assert list(package_store.objects) == [f"packages/weather/0.1.1/{second['sha256']}.esplugin"]
    assert first["id"] != second["id"]


def _stored_menu_icons() -> list[tuple]:
    return [
        (icon.package_id, icon.path, icon.media_type, bytes(icon.icon_bytes))
        for icon in PluginPackageNavigationIcon.objects.order_by("package_id", "path")
    ]


def _data_url(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def test_an_upload_stores_each_menu_icon_once(superadmin_client):
    review = _upload(superadmin_client, build_package(manifest=menu_manifest())).json()

    assert _stored_menu_icons() == [
        (review["id"], "icons/forecast.svg", "image/svg+xml", MENU_ICON_SVG),
        (review["id"], "icons/places.png", "image/png", MENU_ICON_PNG),
    ]


def test_an_upload_without_a_menu_stores_no_menu_icons(superadmin_client):
    _upload(superadmin_client)

    assert not PluginPackageNavigationIcon.objects.exists()


def test_the_review_shows_the_menu_with_each_icon_as_a_data_url(superadmin_client):
    review = _upload(superadmin_client, build_package(manifest=menu_manifest())).json()

    assert review["navigation"] == [
        {"label": "Forecast", "path": "/", "icon_data_url": _data_url("image/svg+xml", MENU_ICON_SVG), "permission": None},
        {"label": "Places", "path": "/places", "icon_data_url": _data_url("image/png", MENU_ICON_PNG), "permission": None},
        {"label": "Saved places", "path": "/places/saved", "icon_data_url": _data_url("image/svg+xml", MENU_ICON_SVG), "permission": None},
    ]
    assert superadmin_client.get(f"{PACKAGES_URL}{review['id']}/review/").json()["navigation"] == review["navigation"]


def test_the_review_shows_which_menu_entries_a_permission_restricts(superadmin_client):
    review = _upload(superadmin_client, build_package(manifest=gated_menu_manifest())).json()

    assert [(entry["label"], entry["permission"]) for entry in review["navigation"]] == [
        ("Forecast", None),
        ("Organization settings", "delete"),
    ]


def test_the_plugin_detail_shows_the_current_package_s_menu(superadmin_client):
    review = _upload(superadmin_client, build_package(manifest=gated_menu_manifest())).json()
    _approve(superadmin_client, review["id"], untrusted_acknowledged=True)

    detail = superadmin_client.get(f"{PLUGINS_URL}weather/").json()

    assert detail["current_package"]["navigation"] == review["navigation"]
    assert [entry["permission"] for entry in detail["current_package"]["navigation"]] == [None, "delete"]


def _queries(client, url) -> int:
    with CaptureQueriesContext(connection) as queries:
        assert client.get(url).status_code == 200
    return len(queries)


def test_the_review_and_the_detail_read_the_menu_icons_in_one_query_whatever_the_menu_s_size(superadmin_client):
    menus = {
        "plain": None,
        "small": [{"label": "Home", "path": "/", "icon": "icons/home.svg"}],
        "full": [{"label": f"Page {index}", "path": f"/page-{index}", "icon": f"icons/page-{index}.svg"} for index in range(12)],
    }
    counts = {}
    for identifier, navigation in menus.items():
        manifest = sample_manifest(id=identifier) if navigation is None else menu_manifest(navigation, id=identifier)
        review = _upload(superadmin_client, build_package(manifest=manifest)).json()
        _approve(superadmin_client, review["id"], untrusted_acknowledged=True)
        counts[identifier] = (
            _queries(superadmin_client, f"{PACKAGES_URL}{review['id']}/review/"),
            _queries(superadmin_client, f"{PLUGINS_URL}{identifier}/"),
        )

    # Both serialize one package's review: its icons cost one query with a menu, none without.
    assert counts["small"] == counts["full"] == tuple(count + 1 for count in counts["plain"])


def test_a_new_upload_deletes_the_replaced_package_s_menu_icons(superadmin_client, django_capture_on_commit_callbacks):
    _upload(superadmin_client, build_package(manifest=menu_manifest()))
    newer = menu_manifest([{"label": "Alerts", "path": "/", "icon": "icons/alerts.svg"}], version="0.1.1")

    with django_capture_on_commit_callbacks(execute=True):
        second = _upload(superadmin_client, build_package(manifest=newer)).json()

    assert _stored_menu_icons() == [(second["id"], "icons/alerts.svg", "image/svg+xml", MENU_ICON_SVG)]


def test_a_menu_problem_refuses_the_upload_and_stores_nothing(superadmin_client, package_store):
    manifest = menu_manifest()
    files = {**sample_files(manifest), "icons/places.png": b"GIF89a"}

    response = _upload(superadmin_client, build_package(files, manifest=manifest))

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_plugin"
    assert response.json()["errors"] == [{"loc": "package.icons/places.png", "message": "is not a PNG image"}]
    assert package_store.objects == {}
    assert not PluginPackageNavigationIcon.objects.exists()


def test_uploading_identical_bytes_again_keeps_the_file(superadmin_client, package_store, django_capture_on_commit_callbacks):
    _upload(superadmin_client)

    with django_capture_on_commit_callbacks(execute=True):
        second = _upload(superadmin_client).json()

    assert PluginPackage.objects.get().pk == second["id"]
    assert len(package_store.objects) == 1


def test_a_newer_version_of_an_approved_plugin_is_put_up_for_review(superadmin_client, package_store):
    review = _upload(superadmin_client).json()
    _approve(superadmin_client, review["id"], untrusted_acknowledged=True)

    response = _upload(superadmin_client, build_package(manifest=sample_manifest(version="0.2.0")))

    assert response.status_code == 201
    body = response.json()
    assert (body["is_upgrade"], body["current_version"], body["review_state"]) == (True, "0.1.0", "pending")
    assert Plugin.objects.get(identifier="weather").current_package_id == review["id"]
    assert len(package_store.objects) == 2


# Shaped like a service-account key, but not one: the scan matches the shape alone.
SECRET_SHAPED_KEY = "esp-" + "Q" * 43


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("backend/src/plugin/settings.py", f'EPICSTAFF_KEY = "{SECRET_SHAPED_KEY}"\n'.encode()),
        ("backend/src/plugin/weather-development-runtime.json", b'{"service_accounts": {}, "secret_settings": {}}'),
    ],
    ids=["service-account-key", "runtime-file"],
)
def test_an_upload_holding_a_key_or_a_runtime_file_is_refused_and_nothing_is_stored(
    superadmin_client, package_store, path, data
):
    manifest = backend_manifest()
    files = {**sample_files(manifest), path: data}

    response = _upload(superadmin_client, build_package(files, manifest=manifest))

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_plugin"
    assert body["errors"] == [
        {"loc": f"package.{path}", "message": "holds an EpicStaff key or runtime file; never package it"}
    ]
    assert SECRET_SHAPED_KEY not in response.content.decode()
    assert package_store.objects == {}
    assert not PluginPackage.objects.exists()
    assert not Plugin.objects.exists()


def test_a_package_with_nothing_to_install_is_invalid(superadmin_client):
    manifest = sample_manifest()
    del manifest["spa"]
    files = {path: data for path, data in sample_files(manifest).items() if not path.startswith("spa/")}

    response = _upload(superadmin_client, build_package(files, manifest=manifest))

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_plugin"
    assert body["errors"] == [
        {"loc": "manifest", "message": "declares neither an spa nor a backend section, so there is nothing to install"}
    ]


def test_a_database_without_a_backend_is_refused(superadmin_client):
    response = _upload(superadmin_client, build_package(manifest=sample_manifest(database={})))

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_plugin"
    assert "manifest.database" in [error["loc"] for error in body["errors"]]
    assert not Plugin.objects.exists()


def test_an_upload_must_be_multipart(superadmin_client):
    response = superadmin_client.post(PACKAGES_URL, {"file": "x"}, format="json")

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"


def test_an_upload_needs_a_file(superadmin_client):
    response = superadmin_client.post(PACKAGES_URL, {}, format="multipart")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid"


def test_a_package_above_the_cap_is_too_large(superadmin_client, settings):
    settings.PLUGINS_MAX_PACKAGE_MB = 0

    response = _upload(superadmin_client)

    assert response.status_code == 413
    assert response.json()["code"] == "package_too_large"


def test_a_request_body_above_the_cap_is_refused_before_parsing(superadmin_client, settings, monkeypatch):
    settings.PLUGINS_MAX_PACKAGE_MB = 0
    monkeypatch.setattr("plugins.views.admin_plugins.MULTIPART_OVERHEAD_BYTES", 0)
    monkeypatch.setattr(
        "plugins.views.admin_plugins.PackageUploadSerializer",
        lambda **kwargs: pytest.fail("the body was parsed"),
    )

    response = _upload(superadmin_client)

    assert response.status_code == 413


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("post", f"{PACKAGES_URL}999999/approve/"),
        ("post", f"{PACKAGES_URL}999999/reject/"),
        ("get", f"{PACKAGES_URL}999999/review/"),
    ],
)
def test_an_unknown_package_is_not_found(superadmin_client, method, url):
    response = getattr(superadmin_client, method)(url, format="json")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_package_not_found"


def test_the_list_is_sorted_by_name_and_summarises_each_plugin(superadmin_client):
    zebra = _upload(superadmin_client, build_package(manifest=sample_manifest(id="zebra", name="Zebra"))).json()
    _approve(superadmin_client, zebra["id"], untrusted_acknowledged=True)
    _upload(superadmin_client, build_package(manifest=sample_manifest(id="alpha", name="alpha tools")))

    response = superadmin_client.get(PLUGINS_URL)

    assert response.status_code == 200
    [alpha, zebra_summary] = response.json()
    assert (alpha["identifier"], zebra_summary["identifier"]) == ("alpha", "zebra")
    assert alpha["state"] == "uploaded"
    assert alpha["current_version"] is None and alpha["icon_url"] is None
    assert alpha["trust"] == "untrusted"
    assert alpha["pending_package"]["version"] == "0.1.0"
    assert zebra_summary["state"] == "running" and zebra_summary["pending_package"] is None
    assert set(zebra_summary) == {
        "identifier", "name", "description", "state", "trust", "current_version", "icon_url",
        "frame_origin", "grant_count", "pending_package", "purge_after", "needs_attention", "upgrade",
        "development", "created_at",
    }
    assert (zebra_summary["purge_after"], zebra_summary["needs_attention"]) == (None, False)
    assert zebra_summary["upgrade"] is None
    assert zebra_summary["development"] is None


def test_the_list_runs_a_fixed_number_of_queries(superadmin_client, django_assert_max_num_queries):
    for identifier in ("one", "two", "three"):
        _upload(superadmin_client, build_package(manifest=sample_manifest(id=identifier)))

    with django_assert_max_num_queries(6):
        response = superadmin_client.get(PLUGINS_URL)

    assert len(response.json()) == 3


def test_the_detail_of_a_plugin_waiting_for_review(superadmin_client):
    review = _upload(superadmin_client).json()

    response = superadmin_client.get(f"{PLUGINS_URL}weather/")

    assert response.status_code == 200
    detail = response.json()
    assert detail["current_package"] is None
    assert detail["pending_package"] == {"id": review["id"], "version": "0.1.0", "trust": "untrusted"}


def test_an_unknown_plugin_is_not_found(superadmin_client):
    response = superadmin_client.get(f"{PLUGINS_URL}missing/")

    assert response.status_code == 404
    assert response.json()["code"] == "plugin_not_found"


UPLOAD_PERMISSION_URL = f"{PACKAGES_URL}upload-permission/"


def test_the_upload_permission_check_lets_a_superadmin_through(superadmin_client):
    response = superadmin_client.get(UPLOAD_PERMISSION_URL)

    assert response.status_code == 204
    assert response.content == b""


ADMIN_ENDPOINTS = [
    ("get", UPLOAD_PERMISSION_URL),
    ("post", PACKAGES_URL),
    ("get", f"{PACKAGES_URL}1/review/"),
    ("post", f"{PACKAGES_URL}1/approve/"),
    ("post", f"{PACKAGES_URL}1/reject/"),
    ("get", PLUGINS_URL),
    ("get", f"{PLUGINS_URL}weather/"),
    ("get", f"{PLUGINS_URL}weather/grants/"),
    ("post", f"{PLUGINS_URL}weather/grants/"),
    ("post", f"{PLUGINS_URL}weather/grants/1/retry-hook/"),
    ("get", f"{PLUGINS_URL}weather/grants/1/suspend-preview/"),
    ("post", f"{PLUGINS_URL}weather/grants/1/suspend/"),
    ("post", f"{PLUGINS_URL}weather/grants/1/resume/"),
    ("post", f"{PLUGINS_URL}weather/upgrade/cancel/"),
    ("post", f"{PLUGINS_URL}weather/upgrade/retry/"),
    ("get", f"{PLUGINS_URL}weather/backups/"),
    ("post", f"{PLUGINS_URL}weather/backups/1/restore/"),
    ("get", f"{PLUGINS_URL}weather/development/"),
    ("put", f"{PLUGINS_URL}weather/development/"),
    ("delete", f"{PLUGINS_URL}weather/development/"),
    ("post", f"{PLUGINS_URL}weather/development/runtime-file/"),
]


@pytest.mark.parametrize(("method", "url"), ADMIN_ENDPOINTS)
def test_an_org_admin_is_refused(client_as, admin_acme, acme, method, url):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = getattr(client, method)(url, format="json")

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


@pytest.mark.parametrize(("method", "url"), ADMIN_ENDPOINTS)
@pytest.mark.parametrize("key_type", ["superadmin user key", "system key"])
def test_api_keys_are_refused_even_a_superadmin_s(issue_api_key, superadmin_user, method, url, key_type):
    raw_key, _ = issue_api_key(user=superadmin_user) if key_type == "superadmin user key" else issue_api_key()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    response = getattr(client, method)(url, format="json")

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


@pytest.mark.parametrize(("method", "url"), ADMIN_ENDPOINTS)
def test_anonymous_callers_must_log_in(anonymous_client, method, url):
    response = getattr(anonymous_client, method)(url, format="json")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


@pytest.mark.parametrize(
    "url",
    [
        PLUGINS_URL,
        PACKAGES_URL,
        "/api/plugins/available/",
        "/api/plugin-public/weather/config/",
        "/api/plugin-public/weather/icons/forecast.svg/",
    ],
)
def test_no_plugin_route_exists_while_the_platform_is_off(superadmin_client, settings, url):
    settings.PLUGINS_ENABLED = False
    reload_root_urlconf()

    assert superadmin_client.get(url).status_code == 404


def test_the_review_icon_is_the_package_icon(superadmin_client):
    review = _upload(superadmin_client).json()

    assert base64.b64decode(review["icon_data_url"].split(",", 1)[1]) == ICON_SVG
    assert PluginPackage.objects.get().review_state == ReviewState.PENDING


def test_the_api_schema_with_the_plugin_routes_renders_as_yaml():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    paths = yaml.safe_load(OpenApiYamlRenderer().render(schema))["paths"]
    assert {
        "/api/admin/plugins/{identifier}/grants/{grant_id}/suspend-preview/",
        "/api/admin/plugins/{identifier}/grants/{grant_id}/suspend/",
        "/api/admin/plugins/{identifier}/grants/{grant_id}/resume/",
    } <= set(paths)



# ---- plugin development mode in the SuperAdmin's list and detail ----


def _summary(client, identifier="weather"):
    return next(plugin for plugin in client.get(PLUGINS_URL).json() if plugin["identifier"] == identifier)


def test_the_list_shows_the_stored_ports_only_while_the_mode_is_on(superadmin_client, running_plugin, settings):
    plugin = running_plugin()
    PluginDevelopmentTarget.objects.create(plugin=plugin, spa_port=5173)

    mode_off = _summary(superadmin_client)["development"]
    settings.PLUGINS_DEV_MODE = True
    mode_on = _summary(superadmin_client)["development"]

    assert (mode_off, mode_on) == (None, {"backend_port": None, "spa_port": 5173})


def test_the_list_shows_no_ports_without_a_target(superadmin_client, running_plugin, settings):
    settings.PLUGINS_DEV_MODE = True
    running_plugin()

    assert _summary(superadmin_client)["development"] is None


@pytest.mark.parametrize("mode", [True, False])
def test_the_detail_says_whether_development_mode_is_on(superadmin_client, running_plugin, settings, mode):
    settings.PLUGINS_DEV_MODE = mode
    running_plugin()

    assert superadmin_client.get(f"{PLUGINS_URL}weather/").json()["development_mode"] is mode


def test_development_adds_no_query_to_the_list(superadmin_client, running_plugin, settings):
    settings.PLUGINS_DEV_MODE = True
    counts = []
    for identifier in ("one", "two", "three", "four", "five"):
        PluginDevelopmentTarget.objects.create(plugin=running_plugin(id=identifier), spa_port=5173)
        if identifier in ("one", "five"):
            with CaptureQueriesContext(connection) as queries:
                assert all(plugin["development"] for plugin in superadmin_client.get(PLUGINS_URL).json())
            counts.append(len(queries))

    assert counts[0] == counts[1]
