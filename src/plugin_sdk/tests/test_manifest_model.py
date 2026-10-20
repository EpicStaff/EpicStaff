import json

import pytest

from epicstaff_plugin.contracts.manifest import (
    PluginManifest,
    manifest_json_schema,
    parse_manifest,
    render_manifest_json_schema,
    validate_manifest,
)
from epicstaff_plugin.problems import PackageProblemsError

BACKEND = {"python": "3.12", "entrypoint": "plugin.app:app"}


def _with_backend(document):
    document["backend"] = dict(BACKEND)
    return document


def _set(path, value, backend=False):
    """Return a mutation that sets `path` (a tuple of keys and indexes) to `value`."""

    def mutate(document):
        if backend:
            _with_backend(document)
        target = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return document

    return mutate


def _delete(*path):
    def mutate(document):
        target = document
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
        return document

    return mutate


ACCESS = [{"resource_type": "flows", "actions": ["read"], "reason": "Reads flows."}]
PUBLIC_PATH = {"path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0}
OUTBOUND_HOST = {"host": "api.example.com", "reason": "Calls the example API."}
SETTING = {"key": "units", "type": "string", "label": "Units", "description": "Which units to use.", "required": False}
LIMITS = {"memory_mb": 256, "db_connections": 5, "statement_timeout_seconds": 10, "requests_per_minute": 60, "cpu_priority": "normal"}


def _public_path(**changes):
    return [{**PUBLIC_PATH, **changes}]


def _setting(**changes):
    return [{**SETTING, **changes}]


def _limits(**changes):
    return {**LIMITS, **changes}


INVALID_CASES = [
    ("manifest_version 2", _set(("manifest_version",), 2), "manifest.manifest_version"),
    ("manifest_version as a string", _set(("manifest_version",), "1"), "manifest.manifest_version"),
    ("upper-case id", _set(("id",), "Weather"), "manifest.id"),
    ("one-character id", _set(("id",), "w"), "manifest.id"),
    ("id ending in a dash", _set(("id",), "weather-"), "manifest.id"),
    ("id longer than 32", _set(("id",), "w" * 33), "manifest.id"),
    ("reserved id admin", _set(("id",), "admin"), "manifest.id"),
    ("reserved id api", _set(("id",), "api"), "manifest.id"),
    ("reserved id plugins", _set(("id",), "plugins"), "manifest.id"),
    ("reserved id packages", _set(("id",), "packages"), "manifest.id"),
    ("reserved pg prefix", _set(("id",), "pgadmin"), "manifest.id"),
    ("version without patch", _set(("version",), "1.0"), "manifest.version"),
    ("version with a leading zero", _set(("version",), "01.0.0"), "manifest.version"),
    ("version with non-ASCII digits", _set(("version",), "١.0.0"), "manifest.version"),
    ("empty name", _set(("name",), ""), "manifest.name"),
    ("blank name", _set(("name",), "   "), "manifest.name"),
    ("name with a newline", _set(("name",), "Wea\nther"), "manifest.name"),
    ("name longer than 64", _set(("name",), "n" * 65), "manifest.name"),
    ("description longer than 500", _set(("description",), "d" * 501), "manifest.description"),
    ("publisher without a name", _delete("publisher", "name"), "manifest.publisher.name"),
    ("publisher url over http", _set(("publisher", "url"), "http://example.com"), "manifest.publisher.url"),
    ("publisher url with credentials", _set(("publisher", "url"), "https://user:pw@example.com"), "manifest.publisher.url"),
    ("icon with another name", _set(("icon",), "logo.svg"), "manifest.icon"),
    ("frame protocol 2", _set(("platform", "frame_protocol"), 2), "manifest.platform.frame_protocol"),
    ("platform without hook_api", _delete("platform", "hook_api"), "manifest.platform.hook_api"),
    ("platform min_epicstaff_version", _set(("platform", "min_epicstaff_version"), "1.0"), "manifest.platform.min_epicstaff_version"),
    ("spa entry escaping spa/", _set(("spa", "entry"), "../index.html"), "manifest.spa.entry"),
    ("spa dir field", _set(("spa", "dir"), "spa/"), "manifest.spa.dir"),
    ("backend python 3.11", _set(("backend",), {**BACKEND, "python": "3.11"}), "manifest.backend.python"),
    ("backend entrypoint without attribute", _set(("backend",), {**BACKEND, "entrypoint": "plugin.app"}), "manifest.backend.entrypoint"),
    ("database with a migrations field", _set(("database",), {"migrations": "database/migrations/"}), "manifest.database.migrations"),
    ("access without a backend", _set(("access",), ACCESS), "manifest.access"),
    ("access action list", _set(("access",), [{**ACCESS[0], "actions": ["list"]}], backend=True), "manifest.access[0].actions[0]"),
    ("access action repeated", _set(("access",), [{**ACCESS[0], "actions": ["read", "read"]}], backend=True), "manifest.access[0].actions"),
    ("access without actions", _set(("access",), [{**ACCESS[0], "actions": []}], backend=True), "manifest.access[0].actions"),
    ("access reason longer than 200", _set(("access",), [{**ACCESS[0], "reason": "r" * 201}], backend=True), "manifest.access[0].reason"),
    ("access resource type twice", _set(("access",), ACCESS * 2, backend=True), "manifest.access"),
    ("access resource type with a dash", _set(("access",), [{**ACCESS[0], "resource_type": "key-value"}], backend=True), "manifest.access[0].resource_type"),
    ("no user_permissions", _delete("user_permissions"), "manifest.user_permissions"),
    ("user_permissions without read", _set(("user_permissions", 0, "action"), "update"), "manifest.user_permissions"),
    (
        "user_permissions action twice",
        lambda document: {**document, "user_permissions": document["user_permissions"] * 2},
        "manifest.user_permissions",
    ),
    (
        "a role with an action but no read",
        lambda document: {
            **document,
            "user_permissions": [
                *document["user_permissions"],
                {"action": "update", "description": "Edit.", "defaults": {"org_admin": True, "member": False, "viewer": True}},
            ],
        },
        "manifest.user_permissions",
    ),
    ("user permission action list", _set(("user_permissions", 0, "action"), "list"), "manifest.user_permissions[0].action"),
    ("defaults without viewer", _delete("user_permissions", 0, "defaults", "viewer"), "manifest.user_permissions[0].defaults.viewer"),
    ("public path without a backend", _set(("public_paths",), [PUBLIC_PATH]), "manifest.public_paths"),
    ("public path outside /api/", _set(("public_paths",), _public_path(path="/ping"), backend=True), "manifest.public_paths[0].path"),
    ("public path /api/ itself", _set(("public_paths",), _public_path(path="/api/"), backend=True), "manifest.public_paths[0].path"),
    ("public path with a dot segment", _set(("public_paths",), _public_path(path="/api/../admin"), backend=True), "manifest.public_paths[0].path"),
    ("public path match regex", _set(("public_paths",), _public_path(match="regex"), backend=True), "manifest.public_paths[0].match"),
    ("public path method TRACE", _set(("public_paths",), _public_path(methods=["TRACE"]), backend=True), "manifest.public_paths[0].methods[0]"),
    ("public path rate 0", _set(("public_paths",), _public_path(rate_limit_per_minute=0), backend=True), "manifest.public_paths[0].rate_limit_per_minute"),
    ("public path body too large", _set(("public_paths",), _public_path(max_body_kb=20481), backend=True), "manifest.public_paths[0].max_body_kb"),
    ("outbound host without a backend", _set(("outbound_hosts",), [OUTBOUND_HOST]), "manifest.outbound_hosts"),
    ("outbound host with a ports field", _set(("outbound_hosts",), [{**OUTBOUND_HOST, "ports": [8443]}], backend=True), "manifest.outbound_hosts[0].ports"),
    ("outbound host with a port", _set(("outbound_hosts",), [{**OUTBOUND_HOST, "host": "api.example.com:443"}], backend=True), "manifest.outbound_hosts[0].host"),
    ("outbound IP literal", _set(("outbound_hosts",), [{**OUTBOUND_HOST, "host": "10.0.0.1"}], backend=True), "manifest.outbound_hosts[0].host"),
    ("outbound upper-case host", _set(("outbound_hosts",), [{**OUTBOUND_HOST, "host": "API.example.com"}], backend=True), "manifest.outbound_hosts[0].host"),
    ("outbound wildcard in the middle", _set(("outbound_hosts",), [{**OUTBOUND_HOST, "host": "api.*.example.com"}], backend=True), "manifest.outbound_hosts[0].host"),
    ("setting without a backend", _set(("settings",), [SETTING]), "manifest.settings"),
    ("setting key with upper case", _set(("settings",), _setting(key="Units"), backend=True), "manifest.settings[0].key"),
    ("setting type float", _set(("settings",), _setting(type="float"), backend=True), "manifest.settings[0].type"),
    ("enum setting without values", _set(("settings",), _setting(type="enum"), backend=True), "manifest.settings[0]"),
    ("string setting with values", _set(("settings",), _setting(values=["a"]), backend=True), "manifest.settings[0]"),
    ("secret setting with a default", _set(("settings",), _setting(type="secret", default="x"), backend=True), "manifest.settings[0]"),
    ("integer setting with a string default", _set(("settings",), _setting(type="integer", default="5"), backend=True), "manifest.settings[0]"),
    ("boolean setting with an integer default", _set(("settings",), _setting(type="boolean", default=1), backend=True), "manifest.settings[0]"),
    ("enum default outside its values", _set(("settings",), _setting(type="enum", values=["a"], default="b"), backend=True), "manifest.settings[0]"),
    ("setting key twice", _set(("settings",), [SETTING, SETTING], backend=True), "manifest.settings"),
    ("limits without a backend", _set(("limits",), LIMITS), "manifest.limits"),
    ("limits memory below 64", _set(("limits",), _limits(memory_mb=63), backend=True), "manifest.limits.memory_mb"),
    ("limits connections above 100", _set(("limits",), _limits(db_connections=101), backend=True), "manifest.limits.db_connections"),
    ("limits cpu priority high", _set(("limits",), _limits(cpu_priority="high"), backend=True), "manifest.limits.cpu_priority"),
    ("limits without requests_per_minute", _set(("limits",), {key: value for key, value in LIMITS.items() if key != "requests_per_minute"}, backend=True), "manifest.limits.requests_per_minute"),
    ("hook without a backend", _set(("hooks",), {"install": True}), "manifest.hooks"),
    ("install timeout above 900", _set(("hooks",), {"install": True, "timeouts_seconds": {"install": 901}}, backend=True), "manifest.hooks.timeouts_seconds.install"),
    ("upgrade timeout above 1800", _set(("hooks",), {"upgrade": True, "timeouts_seconds": {"upgrade": 1801}}, backend=True), "manifest.hooks.timeouts_seconds.upgrade"),
    ("hook flag as a string", _set(("hooks",), {"install": "true"}, backend=True), "manifest.hooks.install"),
    ("unknown top-level field", _set(("ports",), [8443]), "manifest.ports"),
]


@pytest.mark.parametrize(
    ("mutate", "expected_loc"),
    [pytest.param(mutate, loc, id=name) for name, mutate, loc in INVALID_CASES],
)
def test_every_manifest_rule_is_reported_at_its_location(manifest_document, mutate, expected_loc):
    with pytest.raises(PackageProblemsError) as raised:
        validate_manifest(mutate(manifest_document))

    assert expected_loc in [problem.loc for problem in raised.value.problems]


def test_the_weather_sample_is_valid(manifest_document):
    manifest = validate_manifest(manifest_document)

    assert manifest.id == "weather"
    assert manifest.spa.entry == "index.html"
    assert manifest.access == []
    assert manifest.hooks.any_enabled is False


def test_the_complete_example_is_valid(full_manifest_document):
    manifest = validate_manifest(full_manifest_document)

    assert [declaration.resource_type for declaration in manifest.access] == ["flows", "files"]
    assert manifest.settings[0].default == "metric"
    assert manifest.hooks.timeouts_seconds.install == 300


@pytest.mark.parametrize("version", ["0.1.0", "1.0.0-beta.1", "1.0.0+build.5", "10.20.30-rc.1+exp.sha.5114f85"])
def test_semver_versions_are_accepted(manifest_document, version):
    manifest_document["version"] = version

    assert validate_manifest(manifest_document).version == version


@pytest.mark.parametrize("host", ["api.example.com", "*.example.com", "xn--bcher-kva.example"])
def test_dns_names_and_wildcards_are_accepted_outbound_hosts(manifest_document, host):
    _with_backend(manifest_document)
    manifest_document["outbound_hosts"] = [{"host": host, "reason": "Calls it."}]

    assert validate_manifest(manifest_document).outbound_hosts[0].host == host


def test_the_spa_entry_defaults_to_index_html(manifest_document):
    manifest_document["spa"] = {}

    assert validate_manifest(manifest_document).spa.entry == "index.html"


def test_user_permission_defaults_lists_the_actions_a_built_in_role_gets(full_manifest_document):
    manifest = validate_manifest(full_manifest_document)

    assert manifest.user_permission_defaults("org_admin") == ["read", "update", "delete"]
    assert manifest.user_permission_defaults("member") == ["read", "update"]
    assert manifest.user_permission_defaults("viewer") == ["read"]


def test_several_problems_are_reported_together(manifest_document):
    manifest_document["id"] = "API"
    manifest_document["name"] = ""

    with pytest.raises(PackageProblemsError) as raised:
        validate_manifest(manifest_document)

    assert {problem.loc for problem in raised.value.problems} >= {"manifest.id", "manifest.name"}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"\xff\xfe", "not UTF-8"),
        (b"[1, 2]", "JSON object"),
        (b'{"id": "a", "id": "b"}', "more than once"),
        (b'{"manifest_version": NaN}', "not valid JSON"),
        (b"{", "not valid JSON"),
    ],
)
def test_parse_manifest_refuses_bytes_that_are_not_one_strict_json_object(raw, message):
    with pytest.raises(PackageProblemsError) as raised:
        parse_manifest(raw)

    [problem] = raised.value.problems
    assert problem.loc == "manifest"
    assert message in problem.message


def test_parse_manifest_reads_the_sample(manifest_document):
    manifest = parse_manifest(json.dumps(manifest_document).encode("utf-8"))

    assert isinstance(manifest, PluginManifest)


def test_the_json_schema_is_rendered_from_the_model():
    rendered = render_manifest_json_schema()
    schema = json.loads(rendered)

    assert rendered.endswith("}\n")
    assert schema == manifest_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert "user_permissions" in schema["required"]
    assert schema["properties"]["id"]["pattern"] == "^[a-z][a-z0-9-]{0,30}[a-z0-9]$"
