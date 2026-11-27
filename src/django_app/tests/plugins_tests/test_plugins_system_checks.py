"""Start-up checks plugins.E001-E014 and W001, which run only while the plugin platform is on."""

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from epicstaff_plugin.signing import generate_secret_key
from plugins.checks import check_plugin_platform_settings

from tests.plugins_tests.host_template_cases import ACCEPTED, REFUSED

KEY = generate_secret_key().public_key.to_text()
OTHER_KEY = generate_secret_key().public_key.to_text()
PLATFORM_MAXIMUMS = {
    "PLUGINS_MAX_PROCESS_MEMORY_MB": "1024",
    "PLUGINS_MAX_DB_CONNECTIONS": "20",
    "PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS": "60",
    "PLUGINS_MAX_REQUESTS_PER_MINUTE": "600",
    "PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE": "120",
    "PLUGINS_MAX_REQUEST_BODY_MB": "20",
}


@pytest.fixture
def valid_platform(settings):
    """A correct local development setup: every check is quiet."""
    settings.PLUGINS_ENABLED = True
    settings.REFRESH_COOKIE_SECURE = False
    settings.PLUGINS_HOST_TEMPLATE = "{id}.plugins.epicstaff.localhost"
    settings.FRONTEND_BASE_URL = "http://epicstaff.localhost"
    settings.PLUGINS_TRUSTED_SIGNING_KEYS = []
    settings.CORS_ALLOWED_ORIGINS = []
    settings.PLUGINS_GATEWAY_SECRET = "g" * 32
    settings.PLUGINS_NODE_KEY = "k" * 32
    settings.PLUGINS_NODE_UID_RANGE = "20000-20999"
    for setting, value in PLATFORM_MAXIMUMS.items():
        setattr(settings, setting, value)
    settings.PLUGINS_GRACE_PERIOD_DAYS = "30"
    return settings


def _ids():
    return [error.id for error in check_plugin_platform_settings(None)]


def test_a_valid_local_development_setup_passes(valid_platform):
    assert _ids() == []


@pytest.mark.parametrize(
    "template",
    ["{id}.plugins.example.com", "{id}-app.example.com", "app-{id}.example.com", "{id}.example.org.example.com"],
)
def test_a_valid_https_setup_passes(valid_platform, template):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.PLUGINS_HOST_TEMPLATE = template
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com:8443"
    valid_platform.PLUGINS_TRUSTED_SIGNING_KEYS = [f"release:{KEY}", f"backup:{OTHER_KEY}"]

    assert _ids() == []


def test_nothing_is_checked_while_the_platform_is_off(valid_platform):
    valid_platform.PLUGINS_ENABLED = False
    valid_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.invalid"
    valid_platform.FRONTEND_BASE_URL = "not a url"
    valid_platform.PLUGINS_TRUSTED_SIGNING_KEYS = ["broken"]
    valid_platform.PLUGINS_GRACE_PERIOD_DAYS = "abc"

    assert _ids() == []


def test_e001_plain_http_outside_localhost(valid_platform):
    valid_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"

    assert _ids() == ["plugins.E001"]


def test_e001_leaves_an_invalid_template_to_e002(valid_platform):
    valid_platform.PLUGINS_HOST_TEMPLATE = "plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"

    assert _ids() == ["plugins.E002"]


def test_e001_is_quiet_with_a_secure_cookie(valid_platform):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"

    assert _ids() == []


# The words of plugins.E002's message for each rule the shared cases name.
E002_PROBLEMS = {
    "placement": "{id} exactly once, in its first label",
    "parent": "two or more labels",
    "affix": "neither start nor end with a hyphen",
    "label-length": "longer than 63 characters",
    "host-length": "longer than 253 characters",
    "reserved": "reserves for xn-- names",
    "placeholder": "is still a placeholder",
}


@pytest.mark.parametrize(
    ("template", "rule"),
    [
        *REFUSED,
        (None, "placement"),
        ("{ID}.example.com", "placement"),
        ("{id}.Plugins.Example.com", "parent"),
        ("{id}.example.com.", "parent"),
        ("App-{id}.example.com", "affix"),
    ],
)
def test_e002_a_template_that_is_not_valid_or_a_placeholder(valid_platform, template, rule):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    valid_platform.PLUGINS_HOST_TEMPLATE = template

    messages = _messages()

    assert list(messages) == ["plugins.E002"]
    assert E002_PROBLEMS[rule] in messages["plugins.E002"]


@pytest.mark.parametrize("template", ACCEPTED)
def test_e002_accepts_the_shared_valid_templates(valid_platform, template):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    valid_platform.PLUGINS_HOST_TEMPLATE = template

    assert _ids() == []


@pytest.mark.parametrize(
    "url",
    [
        "ftp://epicstaff.example.com",
        "epicstaff.example.com",
        "https://epicstaff.example.com/app",
        "https://user@epicstaff.example.com",
        "https://epicstaff.example.com?x=1",
        "https://epicstaff.example.com:99999",
        "http://epicstaff.example.com",
        "http://localhost:4200",
        'https://epicstaff.test" always; add_header X-Injected 1; #',
        "https://epicstaff test",
        "https://epicstaff.test\n",
        "https://-epicstaff.test",
        "https://epicstaff..test",
        "https://10.0.0.1",
        "https://10.0.0.1:8443",
        "https://0x7f000001",
        "https://[::1]",
        "https://epicstaff.test:0",
        "https://epicstaff.test:8443:1",
        "https://épicstaff.test",
    ],
)
def test_e003_a_frontend_url_that_is_not_an_https_origin_outside_localhost(valid_platform, url):
    valid_platform.FRONTEND_BASE_URL = url

    assert _ids() == ["plugins.E003"]


@pytest.mark.parametrize(
    "entries",
    [
        ["release"],
        [f"release:{KEY[:-4]}"],
        [f"bad name:{KEY}"],
        [f"release:{KEY}", f"release:{OTHER_KEY}"],
        [f"release:{KEY}", f"backup:{KEY}"],
    ],
    ids=["no key", "truncated key", "bad name", "repeated name", "repeated key"],
)
def test_e004_malformed_or_repeated_trusted_keys(valid_platform, entries):
    valid_platform.PLUGINS_TRUSTED_SIGNING_KEYS = entries

    assert _ids() == ["plugins.E004"]


@pytest.mark.parametrize("url", ["HTTPS://EpicStaff.Example.com:8443/", "https://epicstaff-1.example.com"])
def test_e003_accepts_any_case_a_port_and_a_trailing_slash(valid_platform, url):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = url

    assert _ids() == []


@pytest.mark.parametrize(
    "origins",
    [
        ["http://weather.plugins.epicstaff.localhost"],
        ["https://plugins.epicstaff.localhost"],
        ["http://localhost:4200", "https://A.Plugins.Epicstaff.Localhost:8443"],
    ],
    ids=["a plugin host", "the parent itself", "among others, any case"],
)
def test_e005_a_cors_origin_in_the_plugin_zone(valid_platform, origins):
    valid_platform.CORS_ALLOWED_ORIGINS = origins

    assert _ids() == ["plugins.E005"]


@pytest.mark.parametrize(
    ("origins", "errors"),
    [
        (["https://weather-app.example.com"], ["plugins.E005"]),
        (["https://a.weather-app.example.com", "https://x-app.example.com"], ["plugins.E005", "plugins.E005"]),
        (["https://epicstaff.example.com", "https://example.com", "https://app.example.com"], []),
    ],
    ids=["a plugin host", "nested and unknown plugin-shaped hosts", "the zone's other hosts"],
)
def test_e005_with_a_flat_template_judges_only_hosts_of_the_plugin_shape(valid_platform, origins, errors):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    valid_platform.PLUGINS_HOST_TEMPLATE = "{id}-app.example.com"
    valid_platform.CORS_ALLOWED_ORIGINS = origins

    assert _ids() == errors


@pytest.mark.parametrize(
    "origins",
    [None, [], ["http://localhost:4200", "https://epicstaff.localhost", "https://xplugins.epicstaff.localhost"]],
    ids=["none", "empty", "other hosts"],
)
def test_e005_is_quiet_for_origins_outside_the_plugin_zone(valid_platform, origins):
    valid_platform.CORS_ALLOWED_ORIGINS = origins

    assert _ids() == []


def test_the_checks_stop_management_commands(valid_platform):
    valid_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"

    with pytest.raises(SystemCheckError, match="plugins.E001"):
        call_command("check")


@pytest.mark.parametrize("value", ["none", "", "short-secret", "x" * 31])
def test_e006_a_missing_or_short_gateway_secret(valid_platform, value):
    valid_platform.PLUGINS_GATEWAY_SECRET = value

    assert _ids() == ["plugins.E006"]


@pytest.mark.parametrize("value", ["none", "", "x" * 31])
def test_e007_a_missing_or_short_node_key(valid_platform, value):
    valid_platform.PLUGINS_NODE_KEY = value

    assert _ids() == ["plugins.E007"]


@pytest.mark.parametrize(
    "value",
    ["", "20000", "20000-", "abc-def", "10000-10999", "20999-20000", "20000-20008", "50000-60000", "20000 - 20999"],
)
def test_e008_a_malformed_node_uid_range(valid_platform, value):
    valid_platform.PLUGINS_NODE_UID_RANGE = value

    assert _ids() == ["plugins.E008"]


@pytest.mark.parametrize("value", ["10001-10010", "59990-59999", " 20000-20999 "])
def test_e008_accepts_ranges_at_the_bounds(valid_platform, value):
    valid_platform.PLUGINS_NODE_UID_RANGE = value

    assert _ids() == []


@pytest.mark.parametrize("setting", sorted(PLATFORM_MAXIMUMS))
@pytest.mark.parametrize("value", ["0", "-5", "1.5", "lots", ""])
def test_e009_a_platform_maximum_that_is_not_a_positive_integer(valid_platform, setting, value):
    setattr(valid_platform, setting, value)

    assert _ids() == ["plugins.E009"]


@pytest.mark.parametrize(
    ("frontend_url", "template"),
    [
        ("https://plugins.example.com", "{id}.plugins.example.com"),
        ("https://epicstaff.plugins.example.com", "{id}.plugins.example.com"),
        ("https://EpicStaff.Plugins.Example.com:8443", "{id}.plugins.example.com"),
        ("https://example.com", "{id}.example.com"),
        ("https://staff.example.com", "{id}.example.com"),
        ("https://staff-app.example.com", "{id}-app.example.com"),
        ("https://es.staff-app.example.com", "{id}-app.example.com"),
        ("https://app-staff.example.com", "app-{id}.example.com"),
    ],
    ids=[
        "the-parent-itself",
        "a-host-under-it",
        "any-case-and-a-port",
        "a-parent-without-an-affix",
        "a-sibling-without-an-affix",
        "a-host-of-the-suffix-shape",
        "a-host-under-one",
        "a-host-of-the-prefix-shape",
    ],
)
def test_e010_epicstaff_s_host_inside_the_plugin_zone(valid_platform, frontend_url, template):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = frontend_url
    valid_platform.PLUGINS_HOST_TEMPLATE = template

    assert _ids() == ["plugins.E010"]


@pytest.mark.parametrize(
    ("frontend_url", "template"),
    [
        ("https://epicstaff.example.com", "{id}.plugins.example.com"),
        ("https://xplugins.example.com", "{id}.plugins.example.com"),
        ("https://example.com", "{id}.plugins.example.com"),
        ("https://epicstaff.example.com", "{id}-app.example.com"),
        ("https://example.com", "{id}-app.example.com"),
        ("https://app.example.com", "{id}-app.example.com"),
        ("https://staff.example.com", "app-{id}.example.com"),
    ],
    ids=[
        "a-sibling",
        "a-look-alike-suffix",
        "the-parent",
        "a-sibling-in-a-flat-zone",
        "the-parent-of-a-flat-zone",
        "the-bare-suffix",
        "a-sibling-of-a-prefixed-zone",
    ],
)
def test_e010_is_quiet_for_a_host_outside_the_plugin_zone(valid_platform, frontend_url, template):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = frontend_url
    valid_platform.PLUGINS_HOST_TEMPLATE = template

    assert _ids() == []


@pytest.mark.parametrize(
    ("frontend_url", "template"),
    [
        ("https://staff.acme.io", "{id}-app.acme.com"),
        ("https://acme.com", "{id}.plugins.acme.org"),
        ("http://epicstaff.localhost", "{id}.plugins.localhost"),
        ("https://localhost:4200", "{id}-app.plugins.localhost"),
    ],
    ids=["moved-to-another-domain", "another-top-level-domain", "two-localhost-sites", "bare-localhost"],
)
def test_e014_epicstaff_and_the_plugin_hosts_on_different_sites(valid_platform, frontend_url, template):
    valid_platform.FRONTEND_BASE_URL = frontend_url
    valid_platform.PLUGINS_HOST_TEMPLATE = template
    valid_platform.REFRESH_COOKIE_SECURE = True

    messages = _messages()

    assert list(messages) == ["plugins.E014"]
    assert "are not the same site" in messages["plugins.E014"]


@pytest.mark.parametrize(
    ("frontend_url", "template"),
    [
        ("https://epicstaff.example.com", "{id}-app.example.com"),
        ("https://example.com", "{id}-app.example.com"),
        ("https://a.b.example.com", "{id}.plugins.example.com"),
        ("https://EpicStaff.Example.com", "{id}-app.example.com"),
        ("http://epicstaff.localhost", "{id}-app.epicstaff.localhost"),
    ],
    ids=["a-sibling", "the-parent", "deeper-than-the-parent", "any-case", "a-localhost-site"],
)
def test_e014_is_quiet_for_hosts_of_one_site(valid_platform, frontend_url, template):
    valid_platform.FRONTEND_BASE_URL = frontend_url
    valid_platform.PLUGINS_HOST_TEMPLATE = template
    valid_platform.REFRESH_COOKIE_SECURE = True

    assert _ids() == []


@pytest.mark.parametrize("value", ["0", "-1", "abc", "3651", "1.5", ""])
def test_e011_a_grace_period_outside_one_to_3650_days(valid_platform, value):
    valid_platform.PLUGINS_GRACE_PERIOD_DAYS = value

    errors = check_plugin_platform_settings(None)

    assert [error.id for error in errors] == ["plugins.E011"]
    assert errors[0].msg == "PLUGINS_GRACE_PERIOD_DAYS must be a whole number from 1 to 3650."


@pytest.mark.parametrize("value", ["1", "30", "3650", " 7 "])
def test_e011_accepts_one_to_3650_days(valid_platform, value):
    valid_platform.PLUGINS_GRACE_PERIOD_DAYS = value

    assert _ids() == []


# ---- plugin development mode: E012, E013 and W001 ----


def _messages():
    return {message.id: message.msg for message in check_plugin_platform_settings(None)}


@pytest.fixture
def development_platform(valid_platform):
    """A local development deployment with development mode on, under compose: only the warning
    is given.

    DEBUG is set explicitly, because the test runner forces it off. The loopback marker is
    what docker-compose.plugins-dev.yaml sets.
    """
    valid_platform.PLUGINS_DEV_MODE = True
    valid_platform.PLUGINS_DEV_API_PORT = "8082"
    valid_platform.RUN_IN_DOCKER = True
    valid_platform.PLUGINS_DEV_LOOPBACK_ONLY = True
    valid_platform.DEBUG = True
    return valid_platform


def test_development_mode_on_a_local_development_deployment_only_warns(development_platform):
    messages = _messages()

    assert list(messages) == ["plugins.W001"]
    assert messages["plugins.W001"] == (
        "Plugin development mode is on: plugin requests can be served from this machine's ports."
    )


def test_the_warning_does_not_stop_management_commands(development_platform):
    call_command("check")


def test_e012_development_mode_without_debug(development_platform):
    development_platform.DEBUG = False

    messages = _messages()

    assert list(messages) == ["plugins.E012"]
    assert "DJANGO_DEBUG is not true" in messages["plugins.E012"]


@pytest.mark.parametrize(
    "template", ["{id}.plugins.example.com", "{id}.plugins.epicstaff.test", "{id}-app.localhost.example.com"]
)
def test_e012_plugin_hosts_outside_localhost(development_platform, template):
    # A secure cookie, so the plain-http check (E001) stays quiet. EpicStaff stays on
    # epicstaff.localhost, so the plugin hosts are another site as well (E014).
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.PLUGINS_HOST_TEMPLATE = template

    messages = _messages()

    assert list(messages) == ["plugins.E014", "plugins.E012"]
    assert f"PLUGINS_HOST_TEMPLATE ({template!r}) does not end in .localhost" in messages["plugins.E012"]


def test_e012_an_epicstaff_host_outside_localhost(development_platform):
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    development_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"

    messages = _messages()

    assert list(messages) == ["plugins.E012"]
    assert "DJANGO_FRONTEND_BASE_URL ('epicstaff.example.com')" in messages["plugins.E012"]


def test_e012_development_mode_without_the_development_compose_file(development_platform):
    development_platform.PLUGINS_DEV_LOOPBACK_ONLY = False

    messages = _messages()

    assert list(messages) == ["plugins.E012"]
    assert messages["plugins.E012"] == (
        "PLUGINS_DEV_MODE is true, but this is not a local development deployment: "
        "PLUGINS_DEV_LOOPBACK_ONLY is not true in this container, so the stack was not started with "
        "docker-compose.plugins-dev.yaml and EpicStaff's ports may be reachable from other machines."
    )


def test_e012_without_the_development_compose_file_stops_management_commands(development_platform):
    development_platform.PLUGINS_DEV_LOOPBACK_ONLY = False

    with pytest.raises(SystemCheckError, match="plugins.E012"):
        call_command("check")


@pytest.fixture
def development_on_the_host(development_platform):
    """manage.py run on the host: it reads src/.env, whose PLUGINS_DEV_MODE is the compose
    stack's, and no compose file set the loopback marker."""
    development_platform.RUN_IN_DOCKER = False
    development_platform.PLUGINS_DEV_LOOPBACK_ONLY = False
    return development_platform


def test_on_the_host_the_loopback_marker_is_not_checked(development_on_the_host):
    assert _ids() == ["plugins.W001"]
    call_command("check")


def test_on_the_host_every_other_condition_still_holds(development_on_the_host):
    development_on_the_host.DEBUG = False

    messages = _messages()

    assert list(messages) == ["plugins.E012"]
    assert "DJANGO_DEBUG is not true" in messages["plugins.E012"]
    assert "PLUGINS_DEV_LOOPBACK_ONLY" not in messages["plugins.E012"]


def test_the_loopback_marker_alone_neither_turns_development_mode_on_nor_is_checked(valid_platform):
    valid_platform.PLUGINS_DEV_LOOPBACK_ONLY = True

    assert _ids() == []


def test_e012_leaves_an_invalid_template_to_e002(development_platform):
    development_platform.PLUGINS_HOST_TEMPLATE = "plugins.epicstaff.localhost"

    assert _ids() == ["plugins.E002", "plugins.W001"]


def test_e012_names_every_failing_condition(development_platform):
    development_platform.DEBUG = False
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"
    development_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    development_platform.PLUGINS_DEV_LOOPBACK_ONLY = False

    message = _messages()["plugins.E012"]

    assert "DJANGO_DEBUG" in message and "PLUGINS_HOST_TEMPLATE" in message
    assert "DJANGO_FRONTEND_BASE_URL" in message and "PLUGINS_DEV_LOOPBACK_ONLY" in message


def test_e012_stops_management_commands(development_platform):
    development_platform.DEBUG = False

    with pytest.raises(SystemCheckError, match="plugins.E012"):
        call_command("check")


def test_localhost_itself_is_a_local_development_host(development_platform):
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.FRONTEND_BASE_URL = "https://localhost:4200"

    # Development mode allows it (no E012); no plugin host is ever on bare localhost's site.
    assert _ids() == ["plugins.E014", "plugins.W001"]


@pytest.mark.parametrize("value", ["0", "80", "1023", "65536", "abc", "", "8082.0", "-8082"])
def test_e013_a_development_api_port_outside_1024_to_65535(development_platform, value):
    development_platform.PLUGINS_DEV_API_PORT = value

    assert _ids() == ["plugins.E013"]


@pytest.mark.parametrize("value", ["1024", "8082", "65535", " 9000 "])
def test_e013_accepts_ports_from_1024_to_65535(development_platform, value):
    development_platform.PLUGINS_DEV_API_PORT = value

    assert _ids() == ["plugins.W001"]


def test_with_development_mode_off_neither_debug_nor_the_api_port_is_checked(development_platform):
    development_platform.PLUGINS_DEV_MODE = False
    development_platform.DEBUG = False
    development_platform.PLUGINS_DEV_API_PORT = "abc"

    assert _ids() == []


def test_development_mode_is_not_checked_while_the_platform_is_off(development_platform):
    development_platform.PLUGINS_ENABLED = False
    development_platform.DEBUG = False
    development_platform.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"
    development_platform.PLUGINS_DEV_API_PORT = "abc"

    assert _ids() == []
