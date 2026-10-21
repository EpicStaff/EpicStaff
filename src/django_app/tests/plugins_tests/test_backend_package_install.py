"""Packages with a backend: the extra upload rules, and placement at approval."""

import pytest
from plugins.exceptions import PluginNodeFullError
from plugins.models import Plugin, PluginDatabase, PluginPackage, PluginPlacement, PluginState, ReviewState

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import backend_manifest, build_package, sample_files

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PACKAGES_URL = "/api/admin/plugins/packages/"


def _upload(client, data):
    return client.post(PACKAGES_URL, {"file": upload_file(data)}, format="multipart")


def _approve(client, package_id):
    return client.post(f"{PACKAGES_URL}{package_id}/approve/", {"untrusted_acknowledged": True}, format="json")


def _backend_files(manifest, **replaced):
    files = {**sample_files(manifest), **replaced}
    return {path: data for path, data in files.items() if data is not None}


def _locs(response):
    return [error["loc"] for error in response.json()["errors"]]


def test_a_package_with_a_backend_is_accepted(superadmin_client, plugin_node):
    response = _upload(superadmin_client, build_package(manifest=backend_manifest()))

    assert response.status_code == 201
    assert response.json()["contents"]["has_backend"] is True
    assert response.json()["review_state"] == "pending"


def test_a_package_with_a_database_is_accepted(superadmin_client, plugin_node):
    response = _upload(superadmin_client, build_package(manifest=backend_manifest(database={})))

    assert response.status_code == 201
    contents = response.json()["contents"]
    assert (contents["has_database"], contents["migration_count"]) == (True, 1)


def test_a_package_with_a_database_installs(superadmin_client, plugin_node, plugin_database_server):
    package_id = _upload(superadmin_client, build_package(manifest=backend_manifest(database={}))).json()["id"]

    response = _approve(superadmin_client, package_id)

    assert response.status_code == 200
    plugin = Plugin.objects.get()
    assert (plugin.state, plugin.current_package_id) == (PluginState.PROVISIONING, package_id)
    assert PluginPlacement.objects.filter(plugin=plugin).exists()
    assert PluginDatabase.objects.filter(plugin=plugin, database_name="plugin_weather").exists()


@pytest.mark.parametrize(
    ("replaced", "loc"),
    [
        ({"backend/requirements.lock": b"uvicorn==0.52.3\nepicstaff-plugin==0.1.0 --hash=sha256:" + b"b" * 64 + b"\n"}, "package.backend/requirements.lock"),
        ({"backend/requirements.lock": b"uvicorn>=0.50 --hash=sha256:" + b"a" * 64 + b"\n"}, "package.backend/requirements.lock"),
        ({"backend/requirements.lock": b"fastapi==0.141.1 --hash=sha256:" + b"c" * 64 + b"\n"}, "package.backend/requirements.lock"),
        ({"backend/wheels/requests-2.0.0-py3-none-any.whl": b"PK"}, "package.backend/wheels/requests-2.0.0-py3-none-any.whl"),
        ({"backend/src/plugin/app.py": None}, "manifest.backend.entrypoint"),
    ],
    ids=["a pin without a hash", "a range instead of a pin", "uvicorn and the SDK missing", "a wheel the lock does not pin", "no backend/src"],
)
def test_each_backend_layout_rule_is_enforced(superadmin_client, plugin_node, replaced, loc):
    manifest = backend_manifest()

    response = _upload(superadmin_client, build_package(_backend_files(manifest, **replaced), manifest=manifest))

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_plugin"
    assert loc in _locs(response)


def test_a_wheel_the_lock_pins_is_accepted(superadmin_client, plugin_node):
    manifest = backend_manifest()
    files = _backend_files(manifest, **{"backend/wheels/uvicorn-0.52.3-py3-none-any.whl": b"PK"})

    assert _upload(superadmin_client, build_package(files, manifest=manifest)).status_code == 201


@pytest.mark.parametrize(
    ("setting", "manifest_changes", "loc"),
    [
        (("PLUGINS_MAX_PROCESS_MEMORY_MB", "128"), {}, "manifest.limits.memory_mb"),
        (("PLUGINS_MAX_DB_CONNECTIONS", "2"), {}, "manifest.limits.db_connections"),
        (("PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS", "5"), {}, "manifest.limits.statement_timeout_seconds"),
        (("PLUGINS_MAX_REQUESTS_PER_MINUTE", "60"), {}, "manifest.limits.requests_per_minute"),
        (("PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE", "30"), {}, "manifest.public_paths[0].rate_limit_per_minute"),
        (
            ("PLUGINS_MAX_REQUEST_BODY_MB", "1"),
            {"public_paths": [{"path": "/api/upload", "match": "exact", "methods": ["POST"], "rate_limit_per_minute": 10, "max_body_kb": 1025}]},
            "manifest.public_paths[0].max_body_kb",
        ),
    ],
)
def test_a_manifest_above_the_platform_maximums_is_refused(superadmin_client, plugin_node, settings, setting, manifest_changes, loc):
    setattr(settings, *setting)

    response = _upload(superadmin_client, build_package(manifest=backend_manifest(**manifest_changes)))

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_plugin"
    assert _locs(response) == [loc]


def test_a_manifest_at_the_platform_maximums_is_accepted(superadmin_client, plugin_node, settings):
    settings.PLUGINS_MAX_PROCESS_MEMORY_MB = "256"
    settings.PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE = "60"

    assert _upload(superadmin_client, build_package(manifest=backend_manifest())).status_code == 201


def test_approval_places_the_backend_and_sets_provisioning(superadmin_client, plugin_node):
    package_id = _upload(superadmin_client, build_package(manifest=backend_manifest())).json()["id"]

    response = _approve(superadmin_client, package_id)

    assert response.status_code == 200
    assert response.json()["state"] == "provisioning"
    placement = PluginPlacement.objects.get(plugin__identifier="weather")
    assert (placement.node, placement.port, placement.unix_uid) == (plugin_node, 20001, 20000)
    assert (placement.restart_generation, placement.settings_revision) == (0, 0)


def test_each_backend_gets_the_lowest_free_port_and_user_id(backend_plugin):
    first = backend_plugin(id="first")
    second = backend_plugin(id="second")
    first_placement = PluginPlacement.objects.get(plugin=first)
    Plugin.objects.filter(pk=first.pk).delete()

    third = backend_plugin(id="third")

    assert (first_placement.port, first_placement.unix_uid) == (20001, 20000)
    assert (second.placement.port, second.placement.unix_uid) == (20002, 20001)
    assert (third.placement.port, third.placement.unix_uid) == (20001, 20000)


def test_a_full_node_refuses_another_backend(backend_plugin, plugin_node, installation, superadmin):
    plugin_node.port_range_end = plugin_node.port_range_start
    plugin_node.save()
    backend_plugin(id="first")
    data = build_package(manifest=backend_manifest(id="second"))
    package = installation.upload(upload_file(data), len(data), superadmin)

    with pytest.raises(PluginNodeFullError):
        installation.approve(package.pk, superadmin, untrusted_acknowledged=True)

    assert not PluginPlacement.objects.filter(plugin__identifier="second").exists()


def test_approval_without_a_node_is_refused_and_changes_nothing(superadmin_client, spa_root):
    package_id = _upload(superadmin_client, build_package(manifest=backend_manifest())).json()["id"]

    response = _approve(superadmin_client, package_id)

    assert response.status_code == 409
    assert response.json()["code"] == "no_plugin_node"
    assert PluginPackage.objects.get(pk=package_id).review_state == ReviewState.PENDING
    assert Plugin.objects.get(identifier="weather").state == PluginState.UPLOADED
    assert not PluginPlacement.objects.exists()
    assert not (spa_root / "weather" / "current").exists()


def test_a_frontend_only_plugin_still_runs_at_once(superadmin_client, plugin_node):
    package_id = _upload(superadmin_client, build_package()).json()["id"]

    assert _approve(superadmin_client, package_id).json()["state"] == "running"
    assert not PluginPlacement.objects.exists()


def test_approval_checks_the_platform_maximums_again(superadmin_client, plugin_node, settings):
    package_id = _upload(superadmin_client, build_package(manifest=backend_manifest())).json()["id"]
    settings.PLUGINS_MAX_PROCESS_MEMORY_MB = "128"

    response = _approve(superadmin_client, package_id)

    assert response.status_code == 400
    assert _locs(response) == ["manifest.limits.memory_mb"]


def test_a_provisioning_plugin_cannot_be_granted_yet(superadmin_client, backend_plugin, acme):
    backend_plugin()

    response = superadmin_client.post("/api/admin/plugins/weather/grants/", {"organization_id": acme.id}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_not_running"
