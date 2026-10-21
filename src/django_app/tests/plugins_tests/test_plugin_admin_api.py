"""SuperAdmin plugin API: upload, review, approve, reject, list and detail."""

import base64
import os

import pytest
import yaml
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.renderers import OpenApiYamlRenderer
from plugins.models import Plugin, PluginPackage, PluginState, ReviewState
from rest_framework.test import APIClient

from tests.plugins_tests.conftest import reload_root_urlconf, upload_file
from tests.plugins_tests.package_builder import ICON_SVG, INDEX_HTML, build_package, sample_files, sample_manifest

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


def test_uploading_identical_bytes_again_keeps_the_file(superadmin_client, package_store, django_capture_on_commit_callbacks):
    _upload(superadmin_client)

    with django_capture_on_commit_callbacks(execute=True):
        second = _upload(superadmin_client).json()

    assert PluginPackage.objects.get().pk == second["id"]
    assert len(package_store.objects) == 1


def test_a_plugin_with_an_approved_package_cannot_take_a_new_upload(superadmin_client, package_store):
    review = _upload(superadmin_client).json()
    _approve(superadmin_client, review["id"], untrusted_acknowledged=True)

    response = _upload(superadmin_client, build_package(manifest=sample_manifest(version="0.2.0")))

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_upgrade_unavailable"
    assert PluginPackage.objects.count() == 1
    assert len(package_store.objects) == 1


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
        "frame_origin", "grant_count", "pending_package", "purge_after", "needs_attention", "created_at",
    }
    assert (zebra_summary["purge_after"], zebra_summary["needs_attention"]) == (None, False)


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
    [PLUGINS_URL, PACKAGES_URL, "/api/plugins/available/", "/api/plugin-public/weather/config/"],
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
