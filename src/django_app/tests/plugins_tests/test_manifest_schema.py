"""Every manifest v1 rule, as an upload reports it."""

import copy

import pytest
from plugins.exceptions import InvalidPluginError
from plugins.models import Plugin

from tests.plugins_tests.conftest import upload_file
from tests.plugins_tests.package_builder import BACKEND, build_package, sample_manifest

ACCESS = {"resource_type": "flows", "actions": ["read"], "reason": "Reads flows."}
PUBLIC_PATH = {"path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0}
OUTBOUND_HOST = {"host": "api.example.com", "reason": "Calls the example API."}
SETTING = {"key": "units", "type": "string", "label": "Units", "description": "Which units to use.", "required": False}
LIMITS = {"memory_mb": 256, "db_connections": 5, "statement_timeout_seconds": 10, "requests_per_minute": 60, "cpu_priority": "normal"}
READ_ONLY = {"action": "read", "description": "Open it.", "defaults": {"org_admin": True, "member": True, "viewer": True}}


def _manifest(backend=False, **changes):
    manifest = sample_manifest(**changes)
    if backend:
        manifest["backend"] = dict(BACKEND)
    return manifest


def _without(key, *path):
    manifest = sample_manifest()
    target = manifest
    for part in path:
        target = target[part]
    del target[key]
    return manifest


RULES = [
    ("manifest_version is 1", _manifest(manifest_version=2), "manifest.manifest_version"),
    ("id pattern", _manifest(id="Weather"), "manifest.id"),
    ("id at least two characters", _manifest(id="w"), "manifest.id"),
    ("id not ending in a dash", _manifest(id="weather-"), "manifest.id"),
    ("reserved id www", _manifest(id="www"), "manifest.id"),
    ("reserved id api", _manifest(id="api"), "manifest.id"),
    ("reserved id admin", _manifest(id="admin"), "manifest.id"),
    ("reserved id plugins", _manifest(id="plugins"), "manifest.id"),
    ("reserved id epicstaff", _manifest(id="epicstaff"), "manifest.id"),
    ("reserved id static", _manifest(id="static"), "manifest.id"),
    ("reserved id postgres", _manifest(id="postgres"), "manifest.id"),
    ("reserved id public", _manifest(id="public"), "manifest.id"),
    ("reserved id prefix pg", _manifest(id="pgbouncer"), "manifest.id"),
    ("version is SemVer", _manifest(version="1.0"), "manifest.version"),
    ("name 1-64", _manifest(name="n" * 65), "manifest.name"),
    ("name not empty", _manifest(name=""), "manifest.name"),
    ("description 1-500", _manifest(description="d" * 501), "manifest.description"),
    ("publisher name required", _without("name", "publisher"), "manifest.publisher.name"),
    ("publisher url https only", _manifest(publisher={"name": "EpicStaff", "url": "http://example.com"}), "manifest.publisher.url"),
    ("icon is icon.svg or icon.png", _manifest(icon="logo.svg"), "manifest.icon"),
    ("frame_protocol is 1", _manifest(platform={"frame_protocol": 2, "gateway_context": 1, "hook_api": 1}), "manifest.platform.frame_protocol"),
    ("gateway_context is 1", _manifest(platform={"frame_protocol": 1, "gateway_context": 2, "hook_api": 1}), "manifest.platform.gateway_context"),
    ("hook_api is 1", _manifest(platform={"frame_protocol": 1, "gateway_context": 1, "hook_api": 2}), "manifest.platform.hook_api"),
    ("spa entry stays under spa/", _manifest(spa={"entry": "../index.html"}), "manifest.spa.entry"),
    ("backend python 3.12 or 3.13", _manifest(backend=True) | {"backend": {**BACKEND, "python": "3.11"}}, "manifest.backend.python"),
    ("backend entrypoint module:attribute", _manifest(backend=True) | {"backend": {**BACKEND, "entrypoint": "plugin"}}, "manifest.backend.entrypoint"),
    ("database has no fields", _manifest(database={"migrations": "database/migrations/"}), "manifest.database.migrations"),
    ("access without backend", _manifest(access=[ACCESS]), "manifest.access"),
    ("access actions distinct", _manifest(backend=True, access=[{**ACCESS, "actions": ["read", "read"]}]), "manifest.access[0].actions"),
    ("access one entry per type", _manifest(backend=True, access=[ACCESS, ACCESS]), "manifest.access"),
    ("access reason 1-200", _manifest(backend=True, access=[{**ACCESS, "reason": ""}]), "manifest.access[0].reason"),
    ("user_permissions required", _without("user_permissions"), "manifest.user_permissions"),
    ("user_permissions contain read", _manifest(user_permissions=[{**READ_ONLY, "action": "update"}]), "manifest.user_permissions"),
    ("user_permissions distinct", _manifest(user_permissions=[READ_ONLY, READ_ONLY]), "manifest.user_permissions"),
    (
        "a role with any action also gets read",
        _manifest(
            user_permissions=[
                {**READ_ONLY, "defaults": {"org_admin": True, "member": True, "viewer": False}},
                {"action": "update", "description": "Edit.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
            ]
        ),
        "manifest.user_permissions",
    ),
    ("user permission description 1-200", _manifest(user_permissions=[{**READ_ONLY, "description": "d" * 201}]), "manifest.user_permissions[0].description"),
    ("public_paths need backend", _manifest(public_paths=[PUBLIC_PATH]), "manifest.public_paths"),
    ("public path under /api/", _manifest(backend=True, public_paths=[{**PUBLIC_PATH, "path": "/ping"}]), "manifest.public_paths[0].path"),
    ("public path without dot segments", _manifest(backend=True, public_paths=[{**PUBLIC_PATH, "path": "/api/./ping"}]), "manifest.public_paths[0].path"),
    ("public path match", _manifest(backend=True, public_paths=[{**PUBLIC_PATH, "match": "glob"}]), "manifest.public_paths[0].match"),
    ("public path methods", _manifest(backend=True, public_paths=[{**PUBLIC_PATH, "methods": ["CONNECT"]}]), "manifest.public_paths[0].methods[0]"),
    ("public path rate 1-6000", _manifest(backend=True, public_paths=[{**PUBLIC_PATH, "rate_limit_per_minute": 6001}]), "manifest.public_paths[0].rate_limit_per_minute"),
    ("public path body 0-20480", _manifest(backend=True, public_paths=[{**PUBLIC_PATH, "max_body_kb": -1}]), "manifest.public_paths[0].max_body_kb"),
    ("outbound_hosts need backend", _manifest(outbound_hosts=[OUTBOUND_HOST]), "manifest.outbound_hosts"),
    ("outbound host has no ports field", _manifest(backend=True, outbound_hosts=[{**OUTBOUND_HOST, "ports": [8443]}]), "manifest.outbound_hosts[0].ports"),
    ("outbound host has no port", _manifest(backend=True, outbound_hosts=[{**OUTBOUND_HOST, "host": "api.example.com:8443"}]), "manifest.outbound_hosts[0].host"),
    ("outbound host is no IP literal", _manifest(backend=True, outbound_hosts=[{**OUTBOUND_HOST, "host": "192.168.1.1"}]), "manifest.outbound_hosts[0].host"),
    ("outbound host lower case", _manifest(backend=True, outbound_hosts=[{**OUTBOUND_HOST, "host": "Example.com"}]), "manifest.outbound_hosts[0].host"),
    ("settings need backend", _manifest(settings=[SETTING]), "manifest.settings"),
    ("setting key pattern", _manifest(backend=True, settings=[{**SETTING, "key": "1units"}]), "manifest.settings[0].key"),
    ("setting keys unique", _manifest(backend=True, settings=[SETTING, SETTING]), "manifest.settings"),
    ("setting type", _manifest(backend=True, settings=[{**SETTING, "type": "json"}]), "manifest.settings[0].type"),
    ("enum needs values", _manifest(backend=True, settings=[{**SETTING, "type": "enum"}]), "manifest.settings[0]"),
    ("values only for enum", _manifest(backend=True, settings=[{**SETTING, "values": ["a"]}]), "manifest.settings[0]"),
    ("no default for secret", _manifest(backend=True, settings=[{**SETTING, "type": "secret", "default": "x"}]), "manifest.settings[0]"),
    ("limits need backend", _manifest(limits=LIMITS), "manifest.limits"),
    ("memory 64-8192", _manifest(backend=True, limits={**LIMITS, "memory_mb": 8193}), "manifest.limits.memory_mb"),
    ("db connections 1-100", _manifest(backend=True, limits={**LIMITS, "db_connections": 0}), "manifest.limits.db_connections"),
    ("statement timeout 1-600", _manifest(backend=True, limits={**LIMITS, "statement_timeout_seconds": 601}), "manifest.limits.statement_timeout_seconds"),
    ("requests per minute 1-6000", _manifest(backend=True, limits={**LIMITS, "requests_per_minute": 0}), "manifest.limits.requests_per_minute"),
    ("cpu priority normal or low", _manifest(backend=True, limits={**LIMITS, "cpu_priority": "high"}), "manifest.limits.cpu_priority"),
    ("an enabled hook needs backend", _manifest(hooks={"org_removed": True}), "manifest.hooks"),
    ("install timeout at most 900", _manifest(backend=True, hooks={"install": True, "timeouts_seconds": {"install": 901}}), "manifest.hooks.timeouts_seconds.install"),
    ("upgrade timeout at most 1800", _manifest(backend=True, hooks={"upgrade": True, "timeouts_seconds": {"upgrade": 1801}}), "manifest.hooks.timeouts_seconds.upgrade"),
    ("org_removed timeout at most 900", _manifest(backend=True, hooks={"org_removed": True, "timeouts_seconds": {"org_removed": 901}}), "manifest.hooks.timeouts_seconds.org_removed"),
    ("unknown fields are refused", _manifest(ports=[8443]), "manifest.ports"),
    ("min_epicstaff_version was dropped", _manifest(platform={"frame_protocol": 1, "gateway_context": 1, "hook_api": 1, "min_epicstaff_version": "1.0"}), "manifest.platform.min_epicstaff_version"),
]

CATALOG_RULES = [
    ("unknown resource type", {"resource_type": "plugins", "actions": ["read"]}, "manifest.access[0].resource_type"),
    ("use is not an action of agents", {"resource_type": "agents", "actions": ["read", "use"]}, "manifest.access[0].actions[1]"),
    ("update is not an action of secrets", {"resource_type": "secrets", "actions": ["update"]}, "manifest.access[0].actions[0]"),
    ("export is not an action of llm_configs", {"resource_type": "llm_configs", "actions": ["read", "export"]}, "manifest.access[0].actions[1]"),
    ("organizations cannot be declared", {"resource_type": "organizations", "actions": ["create"]}, "manifest.access[0].resource_type"),
    ("audit cannot be declared", {"resource_type": "audit", "actions": ["read", "delete"]}, "manifest.access[0].resource_type"),
]


def _upload_locs(installation, superadmin, manifest) -> list[str]:
    data = build_package(manifest=copy.deepcopy(manifest))
    with pytest.raises(InvalidPluginError) as raised:
        installation.upload(upload_file(data), len(data), superadmin)
    return [error["loc"] for error in raised.value.errors]


@pytest.mark.django_db
@pytest.mark.parametrize(("manifest", "expected_loc"), [pytest.param(m, loc, id=name) for name, m, loc in RULES])
def test_every_manifest_rule_is_reported_at_its_location(installation, superadmin, manifest, expected_loc):
    assert expected_loc in _upload_locs(installation, superadmin, manifest)
    assert not Plugin.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("declaration", "expected_loc"), [pytest.param(d, loc, id=name) for name, d, loc in CATALOG_RULES]
)
def test_access_must_fit_this_epicstaff_s_permission_catalog(installation, superadmin, declaration, expected_loc):
    manifest = _manifest(backend=True, access=[{**declaration, "reason": "Needed."}])

    assert _upload_locs(installation, superadmin, manifest) == [expected_loc]


@pytest.mark.django_db
def test_access_that_fits_the_catalog_is_accepted(installation, superadmin):
    manifest = _manifest(
        backend=True,
        access=[
            {"resource_type": "flows", "actions": ["read", "create", "update", "delete", "export", "use"], "reason": "Runs flows."},
            {"resource_type": "secrets", "actions": ["create", "use"], "reason": "Stores its key."},
        ],
    )
    data = build_package(manifest=manifest)

    package = installation.upload(upload_file(data), len(data), superadmin)

    assert [declaration["resource_type"] for declaration in package.manifest["access"]] == ["flows", "secrets"]


@pytest.mark.django_db
def test_the_upload_api_reports_manifest_problems_in_the_error_envelope(plugins_enabled, package_store, spa_root, superadmin_client):
    data = build_package(manifest=_manifest(id="admin", user_permissions=[{**READ_ONLY, "action": "update"}]))

    response = superadmin_client.post("/api/admin/plugins/packages/", {"file": upload_file(data)}, format="multipart")

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_plugin"
    assert body["status_code"] == 400
    assert {"loc": "manifest.id", "message": "'admin' is reserved"} in body["errors"]
    assert {error["loc"] for error in body["errors"]} >= {"manifest.id", "manifest.user_permissions"}
