import json

import pytest

from pydantic import ValidationError

from epicstaff_plugin.contracts.manifest import (
    ACTIONS,
    MAX_NAVIGATION_ITEMS,
    MAX_NAVIGATION_LABEL_LENGTH,
    MAX_NAVIGATION_PATH_LENGTH,
    MAX_OUTBOUND_HOSTS,
    NAVIGATION_ICON_PATTERN,
    NAVIGATION_PATH_PATTERN,
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


MENU_ITEM = {"label": "Overview", "path": "/", "icon": "icons/overview.svg"}
MENU_ITEM_LOC = "manifest.spa.navigation[0]"


def _menu(**changes):
    """Set `spa.navigation` to one item: `MENU_ITEM` with `changes`."""
    return _set(("spa", "navigation"), [{**MENU_ITEM, **changes}])


def _menu_of(count):
    return [{"label": f"Page {index}", "path": f"/page-{index}", "icon": "icons/page.svg"} for index in range(count)]


MENU_CASES = [
    ("navigation at the top level", _set(("navigation",), [MENU_ITEM]), "manifest.navigation"),
    ("more menu items than the cap", _set(("spa", "navigation"), _menu_of(13)), "manifest.spa.navigation"),
    ("menu path twice", _set(("spa", "navigation"), [MENU_ITEM, {**MENU_ITEM, "label": "Home"}]), "manifest.spa.navigation"),
    ("menu label twice", _set(("spa", "navigation"), [MENU_ITEM, {**MENU_ITEM, "path": "/home"}]), "manifest.spa.navigation"),
    ("menu item with an unknown field", _menu(badge="New"), f"{MENU_ITEM_LOC}.badge"),
    ("menu item without an icon", _set(("spa", "navigation"), [{"label": "A", "path": "/"}]), f"{MENU_ITEM_LOC}.icon"),
    ("menu label empty", _menu(label=""), f"{MENU_ITEM_LOC}.label"),
    ("menu label blank", _menu(label="   "), f"{MENU_ITEM_LOC}.label"),
    ("menu label with a newline", _menu(label="Over\nview"), f"{MENU_ITEM_LOC}.label"),
    ("menu label with a tab", _menu(label="Over\tview"), f"{MENU_ITEM_LOC}.label"),
    ("menu label longer than 32", _menu(label="l" * 33), f"{MENU_ITEM_LOC}.label"),
    ("menu label as a number", _menu(label=1), f"{MENU_ITEM_LOC}.label"),
    ("menu path without a leading slash", _menu(path="projects"), f"{MENU_ITEM_LOC}.path"),
    ("menu path empty", _menu(path=""), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a trailing slash", _menu(path="/a/"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with an empty segment", _menu(path="/a//b"), f"{MENU_ITEM_LOC}.path"),
    ("menu path of two slashes", _menu(path="//"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a query", _menu(path="/a?x=1"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a percent escape", _menu(path="/a%20b"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a fragment", _menu(path="/a#b"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a .. segment", _menu(path="/a/.."), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a . segment", _menu(path="/./a"), f"{MENU_ITEM_LOC}.path"),
    ("menu path of one dot", _menu(path="/."), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a space", _menu(path="/a b"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a non-ASCII letter", _menu(path="/café"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a trailing newline", _menu(path="/a\n"), f"{MENU_ITEM_LOC}.path"),
    ("menu path with a backslash", _menu(path="/a\\b"), f"{MENU_ITEM_LOC}.path"),
    ("menu path as an absolute URL", _menu(path="https://example.com/"), f"{MENU_ITEM_LOC}.path"),
    ("menu path longer than 256", _menu(path="/" + "p" * 256), f"{MENU_ITEM_LOC}.path"),
    ("menu icon with upper case", _menu(icon="icons/A.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon as a GIF", _menu(icon="icons/a.gif"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon with an upper-case extension", _menu(icon="icons/a.SVG"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon in a subfolder", _menu(icon="icons/sub/a.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon outside icons/", _menu(icon="icon.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon in spa/", _menu(icon="spa/icons/a.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon with an absolute path", _menu(icon="/icons/a.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon without a name", _menu(icon="icons/.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon starting with a dash", _menu(icon="icons/-a.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon with a dot-dot name", _menu(icon="icons/../a.svg"), f"{MENU_ITEM_LOC}.icon"),
    ("menu icon name longer than 63", _menu(icon="icons/" + "i" * 64 + ".svg"), f"{MENU_ITEM_LOC}.icon"),
]


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
    ("database without a backend", _set(("database",), {}), "manifest.database"),
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
                {"action": "update", "description": "Edit.", "defaults": {"org_admin": True, "member": True, "viewer": True}},
            ],
        },
        "manifest.user_permissions",
    ),
    (
        "viewer gets an action member does not",
        _set(("user_permissions", 0, "defaults"), {"org_admin": True, "member": False, "viewer": True}),
        "manifest.user_permissions[0].defaults",
    ),
    (
        "member gets an action org_admin does not",
        _set(("user_permissions", 0, "defaults"), {"org_admin": False, "member": True, "viewer": False}),
        "manifest.user_permissions[0].defaults",
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
    (
        "more outbound hosts than the cap",
        _set(("outbound_hosts",), [{**OUTBOUND_HOST, "host": f"api{index}.example.com"} for index in range(101)], backend=True),
        "manifest.outbound_hosts",
    ),
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
    ("limits requests_per_minute as a string", _set(("limits",), _limits(requests_per_minute="60"), backend=True), "manifest.limits.requests_per_minute"),
    ("limits with an unknown field", _set(("limits",), _limits(disk_mb=10), backend=True), "manifest.limits.disk_mb"),
    ("hook without a backend", _set(("hooks",), {"install": True}), "manifest.hooks"),
    ("install timeout above 900", _set(("hooks",), {"install": True, "timeouts_seconds": {"install": 901}}, backend=True), "manifest.hooks.timeouts_seconds.install"),
    ("upgrade timeout above 1800", _set(("hooks",), {"upgrade": True, "timeouts_seconds": {"upgrade": 1801}}, backend=True), "manifest.hooks.timeouts_seconds.upgrade"),
    ("hook flag as a string", _set(("hooks",), {"install": "true"}, backend=True), "manifest.hooks.install"),
    ("unknown top-level field", _set(("ports",), [8443]), "manifest.ports"),
]


@pytest.mark.parametrize(
    ("mutate", "expected_loc"),
    [pytest.param(mutate, loc, id=name) for name, mutate, loc in [*INVALID_CASES, *MENU_CASES]],
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


@pytest.mark.parametrize(
    "limits",
    [{"memory_mb": 256}, {"cpu_priority": "low", "requests_per_minute": 30}, {}, {"memory_mb": None}],
)
def test_every_limit_may_be_left_to_the_platform_default(manifest_document, limits):
    manifest = validate_manifest(_set(("limits",), limits, backend=True)(manifest_document))

    given = {key: value for key, value in limits.items() if value is not None}
    assert manifest.limits.model_dump(exclude_none=True) == given


@pytest.mark.parametrize(
    "defaults",
    [
        {"org_admin": True, "member": True, "viewer": True},
        {"org_admin": True, "member": True, "viewer": False},
        {"org_admin": True, "member": False, "viewer": False},
        {"org_admin": False, "member": False, "viewer": False},
    ],
)
def test_nested_built_in_role_defaults_are_accepted(manifest_document, defaults):
    manifest_document["user_permissions"].append({"action": "update", "description": "Edit.", "defaults": defaults})
    manifest_document["user_permissions"][0]["defaults"] = {"org_admin": True, "member": True, "viewer": True}

    assert validate_manifest(manifest_document).user_permissions[1].defaults.model_dump() == defaults


def test_a_built_in_role_default_that_is_not_nested_says_which_roles(manifest_document):
    manifest_document["user_permissions"][0]["defaults"] = {"org_admin": True, "member": False, "viewer": True}

    with pytest.raises(PackageProblemsError) as raised:
        validate_manifest(manifest_document)

    (problem,) = raised.value.problems
    assert problem.loc == "manifest.user_permissions[0].defaults"
    assert "gives viewer the action but not member" in problem.message


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


def test_a_database_without_a_backend_is_refused_as_requires_backend(manifest_document):
    manifest_document["database"] = {}

    with pytest.raises(ValidationError) as raised:
        PluginManifest.model_validate(manifest_document)

    (error,) = raised.value.errors()
    assert (error["loc"], error["type"], error["msg"]) == (("database",), "requires_backend", "needs a backend section")


def test_a_database_with_a_backend_is_accepted(manifest_document):
    _with_backend(manifest_document)
    manifest_document["database"] = {}

    assert validate_manifest(manifest_document).database is not None


def test_the_outbound_host_cap_is_one_hundred(manifest_document):
    _with_backend(manifest_document)
    manifest_document["outbound_hosts"] = [
        {"host": f"api{index}.example.com", "reason": "Calls it."} for index in range(MAX_OUTBOUND_HOSTS)
    ]

    assert MAX_OUTBOUND_HOSTS == 100
    assert len(validate_manifest(manifest_document).outbound_hosts) == 100


def test_the_json_schema_caps_outbound_hosts():
    assert manifest_json_schema()["properties"]["outbound_hosts"]["maxItems"] == MAX_OUTBOUND_HOSTS


def test_the_spa_entry_defaults_to_index_html(manifest_document):
    manifest_document["spa"] = {}

    assert validate_manifest(manifest_document).spa.entry == "index.html"


def test_an_app_without_a_menu_has_an_empty_one(manifest_document):
    manifest = validate_manifest(manifest_document)

    assert manifest.spa.navigation == []
    assert manifest.navigation_icon_paths == ()


@pytest.mark.parametrize(
    "path",
    ["/", "/projects", "/a/b-c_d.e~f", "/Projects/2026/Q4", "/.../a..b/.c/d.", "/" + "p" * (MAX_NAVIGATION_PATH_LENGTH - 1)],
    ids=["root", "one segment", "every punctuation allowed", "mixed case and digits", "dots that are not dot segments", "longest"],
)
def test_menu_paths_of_plain_segments_are_accepted(manifest_document, path):
    manifest_document["spa"]["navigation"] = [{**MENU_ITEM, "path": path}]

    assert validate_manifest(manifest_document).spa.navigation[0].path == path


@pytest.mark.parametrize(
    "icon",
    ["icons/overview.svg", "icons/projects.png", "icons/0.svg", "icons/a_b-c.png", "icons/" + "i" * 63 + ".svg"],
)
def test_menu_icons_named_by_the_rule_are_accepted(manifest_document, icon):
    manifest_document["spa"]["navigation"] = [{**MENU_ITEM, "icon": icon}]

    assert validate_manifest(manifest_document).spa.navigation[0].icon == icon


def test_a_full_menu_may_share_icons_and_lists_each_icon_once(manifest_document):
    manifest_document["spa"]["navigation"] = [
        {"label": "l" * MAX_NAVIGATION_LABEL_LENGTH, "path": "/", "icon": "icons/b.svg"},
        *({"label": f"Page {index}", "path": f"/page-{index}", "icon": "icons/a.png"} for index in range(1, MAX_NAVIGATION_ITEMS)),
    ]

    manifest = validate_manifest(manifest_document)

    assert len(manifest.spa.navigation) == MAX_NAVIGATION_ITEMS == 12
    assert manifest.navigation_icon_paths == ("icons/a.png", "icons/b.svg")


def test_a_menu_entry_names_no_permission_unless_it_says_so(manifest_document):
    manifest_document["spa"]["navigation"] = [MENU_ITEM, {**MENU_ITEM, "label": "Home", "path": "/home", "permission": None}]

    assert [item.permission for item in validate_manifest(manifest_document).spa.navigation] == [None, None]


@pytest.mark.parametrize("action", ["read", "update", "delete"])
def test_a_menu_entry_may_name_any_action_user_permissions_declares(full_manifest_document, action):
    full_manifest_document["spa"]["navigation"] = [{**MENU_ITEM, "permission": action}]

    assert validate_manifest(full_manifest_document).spa.navigation[0].permission == action


def test_every_menu_entry_naming_an_undeclared_action_is_reported_at_its_own_index(full_manifest_document):
    # The complete example declares read, update and delete; drop delete.
    full_manifest_document["user_permissions"] = full_manifest_document["user_permissions"][:2]
    full_manifest_document["spa"]["navigation"] = [
        {**MENU_ITEM, "permission": "update"},
        {"label": "Reports", "path": "/reports", "icon": "icons/reports.svg", "permission": "export"},
        {"label": "Places", "path": "/places", "icon": "icons/places.svg"},
        {"label": "Settings", "path": "/settings", "icon": "icons/settings.svg", "permission": "delete"},
    ]

    with pytest.raises(PackageProblemsError) as raised:
        validate_manifest(full_manifest_document)

    assert [problem.as_dict() for problem in raised.value.problems] == [
        {"loc": "manifest.spa.navigation[1].permission", "message": "names 'export', which user_permissions does not declare"},
        {"loc": "manifest.spa.navigation[3].permission", "message": "names 'delete', which user_permissions does not declare"},
    ]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Projects", "projects"),
        ("Projects", "PROJECTS"),
        ("Projects", "\uff30rojects"),
        ("Projects", "\uff30\uff32\uff2f\uff2a\uff25\uff23\uff34\uff33"),
        ("Straße", "STRASSE"),
        ("Files", "\ufb01les"),
        ("Page 2", "Page \u00b2"),
    ],
    ids=["lower case", "upper case", "a fullwidth letter", "all fullwidth", "sharp s", "fi ligature", "superscript digit"],
)
def test_menu_labels_differing_only_in_case_or_compatibility_form_are_one_label(manifest_document, first, second):
    manifest_document["spa"]["navigation"] = [MENU_ITEM, {**MENU_ITEM, "label": first, "path": "/a"}, {**MENU_ITEM, "label": second, "path": "/b"}]

    with pytest.raises(ValidationError) as raised:
        PluginManifest.model_validate(manifest_document)

    (error,) = raised.value.errors()
    assert (error["loc"], error["type"], error["msg"]) == (("spa", "navigation"), "duplicate", f"lists label '{second}' more than once")


LABEL_WHITESPACE_MESSAGE = "must not start or end with whitespace"
INVISIBLE_CHARACTER_MESSAGE = "must not contain invisible formatting characters"
PLAIN_SPACES_MESSAGE = "must not contain whitespace other than plain spaces"
VISIBLE_CHARACTER_MESSAGE = "must contain at least one visible character"


# The plugin documentation quotes these messages; a change here is a change there.
@pytest.mark.parametrize(
    ("label", "error_type", "message"),
    [
        ("Over\u202eview", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("\u2066Overview\u2069", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("Over\u200bview", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("\u200b", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("\ufeffOverview", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("Over\u00adview", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("Over\ufff9view", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("\u3164", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("Projects\u034f", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("\ufe0fX", "invisible_character", INVISIBLE_CHARACTER_MESSAGE),
        ("Proj\u2028ects", "whitespace_character", PLAIN_SPACES_MESSAGE),
        ("Proj\u2029ects", "whitespace_character", PLAIN_SPACES_MESSAGE),
        ("Proj\u00a0ects", "whitespace_character", PLAIN_SPACES_MESSAGE),
        ("Proj\u3000ects", "whitespace_character", PLAIN_SPACES_MESSAGE),
        ("Proj\u2003ects", "whitespace_character", PLAIN_SPACES_MESSAGE),
        ("Proj\tects", "control_character", "must not contain control characters"),
        ("\u2800", "visible_character_required", VISIBLE_CHARACTER_MESSAGE),
        ("\u2800 \u2800", "visible_character_required", VISIBLE_CHARACTER_MESSAGE),
        (" Overview", "label_whitespace", LABEL_WHITESPACE_MESSAGE),
        ("Overview ", "label_whitespace", LABEL_WHITESPACE_MESSAGE),
        ("Overview\u00a0", "label_whitespace", LABEL_WHITESPACE_MESSAGE),
    ],
    ids=[
        "right-to-left override",
        "left-to-right isolate",
        "zero-width space",
        "only a zero-width space",
        "byte order mark",
        "soft hyphen",
        "interlinear annotation anchor",
        "only a hangul filler",
        "combining grapheme joiner",
        "variation selector",
        "line separator",
        "paragraph separator",
        "no-break space",
        "ideographic space",
        "em space",
        "tab",
        "only a braille blank",
        "braille blanks and a space",
        "leading space",
        "trailing space",
        "trailing no-break space",
    ],
)
def test_a_menu_label_refuses_what_would_hide_or_disguise_its_text(manifest_document, label, error_type, message):
    manifest_document["spa"]["navigation"] = [{**MENU_ITEM, "label": label}]

    with pytest.raises(ValidationError) as raised:
        PluginManifest.model_validate(manifest_document)

    (error,) = raised.value.errors()
    assert (error["loc"], error["type"], error["msg"]) == (("spa", "navigation", 0, "label"), error_type, message)


# The first and the last code point of every Default_Ignorable_Code_Point range of Unicode
# 17.0.0 (DerivedCoreProperties.txt); a range of one code point is listed once.
DEFAULT_IGNORABLE_BOUNDARIES = [
    0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180F, 0x200B, 0x200F, 0x202A, 0x202E,
    0x2060, 0x206F, 0x3164, 0xFE00, 0xFE0F, 0xFEFF, 0xFFA0, 0xFFF0, 0xFFF8, 0x1BCA0, 0x1BCA3, 0x1D173, 0x1D17A,
    0xE0000, 0xE0FFF,
]


@pytest.mark.parametrize("code_point", DEFAULT_IGNORABLE_BOUNDARIES, ids=lambda code_point: f"U+{code_point:04X}")
def test_every_default_ignorable_code_point_range_is_refused_in_a_menu_label(manifest_document, code_point):
    manifest_document["spa"]["navigation"] = [{**MENU_ITEM, "label": f"Over{chr(code_point)}view"}]

    with pytest.raises(ValidationError) as raised:
        PluginManifest.model_validate(manifest_document)

    (error,) = raised.value.errors()
    assert (error["type"], error["msg"]) == ("invisible_character", INVISIBLE_CHARACTER_MESSAGE)


@pytest.mark.parametrize(
    "label",
    ["Saved places", "Прогноз погоди", "天気 予報", "Météo à venir", "Ünits & más", "A B C", "Report 2026", "\u2800Braille"],
    ids=["inner space", "cyrillic", "japanese", "accented latin", "symbols", "single spaces", "digits", "a braille blank and letters"],
)
def test_a_menu_label_with_inner_spaces_and_letters_of_any_script_is_accepted(manifest_document, label):
    manifest_document["spa"]["navigation"] = [{**MENU_ITEM, "label": label}]

    assert validate_manifest(manifest_document).spa.navigation[0].label == label


def test_distinct_menu_labels_of_different_scripts_are_accepted(manifest_document):
    labels = ["Overview", "Огляд", "概要", "Projects"]
    manifest_document["spa"]["navigation"] = [{**MENU_ITEM, "label": label, "path": f"/page-{index}"} for index, label in enumerate(labels)]

    assert [item.label for item in validate_manifest(manifest_document).spa.navigation] == labels


PATH_MESSAGE = (
    "must be '/' or '/'-separated segments of letters, digits, '-', '.', '_' and '~', "
    "without a query, a '.' or '..' segment, or a trailing '/'"
)
ICON_MESSAGE = (
    "must be icons/<name>.svg or icons/<name>.png, where <name> is 1 to 63 lower-case "
    "letters, digits, '-' and '_', starting with a letter or a digit"
)


# The plugin documentation quotes these messages; a change here is a change there.
@pytest.mark.parametrize(
    ("navigation", "loc", "error_type", "message"),
    [
        ([{**MENU_ITEM, "path": "/a/"}], ("spa", "navigation", 0, "path"), "navigation_path", PATH_MESSAGE),
        ([{**MENU_ITEM, "path": "/a/.."}], ("spa", "navigation", 0, "path"), "navigation_path", PATH_MESSAGE),
        ([{**MENU_ITEM, "path": "/" + "p" * 256}], ("spa", "navigation", 0, "path"), "string_too_long", "String should have at most 256 characters"),
        ([{**MENU_ITEM, "icon": "icons/sub/a.svg"}], ("spa", "navigation", 0, "icon"), "navigation_icon", ICON_MESSAGE),
        ([{**MENU_ITEM, "label": "  "}], ("spa", "navigation", 0, "label"), "blank_text", "must not be blank"),
        ([{**MENU_ITEM, "label": "A\x7fB"}], ("spa", "navigation", 0, "label"), "control_character", "must not contain control characters"),
        ([{**MENU_ITEM, "label": "l" * 33}], ("spa", "navigation", 0, "label"), "string_too_long", "String should have at most 32 characters"),
        ([MENU_ITEM, {**MENU_ITEM, "label": "Home"}], ("spa", "navigation"), "duplicate", "lists path '/' more than once"),
        ([MENU_ITEM, {**MENU_ITEM, "path": "/home"}], ("spa", "navigation"), "duplicate", "lists label 'Overview' more than once"),
        (_menu_of(13), ("spa", "navigation"), "too_long", "List should have at most 12 items after validation, not 13"),
        ([{**MENU_ITEM, "permission": "delete"}], ("spa", "navigation", 0, "permission"), "undeclared_permission", "names 'delete', which user_permissions does not declare"),
        ([{**MENU_ITEM, "permission": "list"}], ("spa", "navigation", 0, "permission"), "literal_error", "Input should be 'read', 'create', 'update', 'delete', 'export' or 'use'"),
    ],
    ids=[
        "trailing slash", "dot-dot segment", "path too long", "icon in a subfolder", "blank label", "control character", "label too long",
        "path twice", "label twice", "too many items", "undeclared permission", "permission that is no action",
    ],
)
def test_a_menu_rule_says_exactly_what_is_wrong(manifest_document, navigation, loc, error_type, message):
    manifest_document["spa"]["navigation"] = navigation

    with pytest.raises(ValidationError) as raised:
        PluginManifest.model_validate(manifest_document)

    (error,) = raised.value.errors()
    assert (error["loc"], error["type"], error["msg"]) == (loc, error_type, message)


def test_the_json_schema_describes_the_menu():
    schema = manifest_json_schema()
    item = schema["$defs"]["NavigationItem"]

    assert "navigation" not in schema["properties"]
    assert schema["$defs"]["Spa"]["properties"]["navigation"]["maxItems"] == MAX_NAVIGATION_ITEMS
    assert item["required"] == ["label", "path", "icon"]
    assert item["additionalProperties"] is False
    assert (item["properties"]["label"]["minLength"], item["properties"]["label"]["maxLength"]) == (1, 32)
    assert item["properties"]["path"]["pattern"] == NAVIGATION_PATH_PATTERN
    assert item["properties"]["path"]["maxLength"] == 256
    assert item["properties"]["icon"]["pattern"] == NAVIGATION_ICON_PATTERN
    assert item["properties"]["permission"]["anyOf"] == [{"enum": list(ACTIONS), "type": "string"}, {"type": "null"}]
    assert item["properties"]["permission"]["default"] is None


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
