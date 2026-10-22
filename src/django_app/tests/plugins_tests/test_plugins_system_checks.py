"""Start-up checks plugins.E001-E013 and W001, which run only while the plugin platform is on."""

import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from epicstaff_plugin.signing import generate_secret_key
from plugins.checks import check_plugin_platform_settings

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
    settings.PLUGINS_BASE_DOMAIN = "plugins.epicstaff.localhost"
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


def test_a_valid_https_setup_passes(valid_platform):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.PLUGINS_BASE_DOMAIN = "plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com:8443"
    valid_platform.PLUGINS_TRUSTED_SIGNING_KEYS = [f"release:{KEY}", f"backup:{OTHER_KEY}"]

    assert _ids() == []


def test_nothing_is_checked_while_the_platform_is_off(valid_platform):
    valid_platform.PLUGINS_ENABLED = False
    valid_platform.PLUGINS_BASE_DOMAIN = "plugins.invalid"
    valid_platform.FRONTEND_BASE_URL = "not a url"
    valid_platform.PLUGINS_TRUSTED_SIGNING_KEYS = ["broken"]
    valid_platform.PLUGINS_GRACE_PERIOD_DAYS = "abc"

    assert _ids() == []


def test_e001_plain_http_outside_localhost(valid_platform):
    valid_platform.PLUGINS_BASE_DOMAIN = "plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"

    assert _ids() == ["plugins.E001"]


def test_e001_is_quiet_with_a_secure_cookie(valid_platform):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.PLUGINS_BASE_DOMAIN = "plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"

    assert _ids() == []


@pytest.mark.parametrize(
    "domain",
    ["plugins.invalid", "Plugins.Example.com", "plugins_example.com", "localhost", "-plugins.example.com", "plugins..example.com", None],
)
def test_e002_a_base_domain_that_is_not_a_lower_case_dns_name_or_a_placeholder(valid_platform, domain):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    valid_platform.PLUGINS_BASE_DOMAIN = domain

    assert _ids() == ["plugins.E002"]


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
    valid_platform.PLUGINS_BASE_DOMAIN = "plugins.example.com"
    valid_platform.FRONTEND_BASE_URL = url

    assert _ids() == []


@pytest.mark.parametrize(
    "origins",
    [
        ["http://weather.plugins.epicstaff.localhost"],
        ["https://plugins.epicstaff.localhost"],
        ["http://localhost:4200", "https://A.Plugins.Epicstaff.Localhost:8443"],
    ],
    ids=["a plugin host", "the base domain itself", "among others, any case"],
)
def test_e005_a_cors_origin_under_the_plugin_base_domain(valid_platform, origins):
    valid_platform.CORS_ALLOWED_ORIGINS = origins

    assert _ids() == ["plugins.E005"]


@pytest.mark.parametrize(
    "origins",
    [None, [], ["http://localhost:4200", "https://epicstaff.localhost", "https://xplugins.epicstaff.localhost"]],
    ids=["none", "empty", "other hosts"],
)
def test_e005_is_quiet_for_origins_outside_the_plugin_base_domain(valid_platform, origins):
    valid_platform.CORS_ALLOWED_ORIGINS = origins

    assert _ids() == []


def test_the_checks_stop_management_commands(valid_platform):
    valid_platform.PLUGINS_BASE_DOMAIN = "plugins.example.com"

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
    ("frontend_url", "base_domain"),
    [
        ("https://plugins.example.com", "plugins.example.com"),
        ("https://epicstaff.plugins.example.com", "plugins.example.com"),
        ("https://EpicStaff.Plugins.Example.com:8443", "plugins.example.com"),
        ("https://example.com", "example.com"),
    ],
    ids=["the-base-domain-itself", "a-host-under-it", "any-case-and-a-port", "a-parent-domain-as-base"],
)
def test_e010_epicstaff_s_host_inside_the_plugin_base_domain(valid_platform, frontend_url, base_domain):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = frontend_url
    valid_platform.PLUGINS_BASE_DOMAIN = base_domain

    assert _ids() == ["plugins.E010"]


@pytest.mark.parametrize(
    ("frontend_url", "base_domain"),
    [
        ("https://epicstaff.example.com", "plugins.example.com"),
        ("https://xplugins.example.com", "plugins.example.com"),
        ("https://example.com", "plugins.example.com"),
    ],
    ids=["a-sibling", "a-look-alike-suffix", "the-parent"],
)
def test_e010_is_quiet_for_a_host_outside_the_plugin_base_domain(valid_platform, frontend_url, base_domain):
    valid_platform.REFRESH_COOKIE_SECURE = True
    valid_platform.FRONTEND_BASE_URL = frontend_url
    valid_platform.PLUGINS_BASE_DOMAIN = base_domain

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
    """A local development deployment with development mode on: only the warning is given.

    DEBUG is set explicitly, because the test runner forces it off.
    """
    valid_platform.PLUGINS_DEV_MODE = True
    valid_platform.PLUGINS_DEV_API_PORT = "8082"
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


@pytest.mark.parametrize("base_domain", ["plugins.example.com", "plugins.epicstaff.test", "plugins.localhost.example.com"])
def test_e012_a_plugin_base_domain_outside_localhost(development_platform, base_domain):
    # A secure cookie, so the plain-http check (E001) stays quiet and only this one speaks.
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.PLUGINS_BASE_DOMAIN = base_domain

    messages = _messages()

    assert list(messages) == ["plugins.E012"]
    assert f"PLUGINS_BASE_DOMAIN ({base_domain!r}) does not end in .localhost" in messages["plugins.E012"]


def test_e012_an_epicstaff_host_outside_localhost(development_platform):
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"

    messages = _messages()

    assert list(messages) == ["plugins.E012"]
    assert "DJANGO_FRONTEND_BASE_URL ('epicstaff.example.com')" in messages["plugins.E012"]


def test_e012_names_every_failing_condition(development_platform):
    development_platform.DEBUG = False
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.PLUGINS_BASE_DOMAIN = "plugins.example.com"
    development_platform.FRONTEND_BASE_URL = "https://epicstaff.example.com"

    message = _messages()["plugins.E012"]

    assert "DJANGO_DEBUG" in message and "PLUGINS_BASE_DOMAIN" in message
    assert "DJANGO_FRONTEND_BASE_URL" in message


def test_e012_stops_management_commands(development_platform):
    development_platform.DEBUG = False

    with pytest.raises(SystemCheckError, match="plugins.E012"):
        call_command("check")


def test_localhost_itself_is_a_local_development_host(development_platform):
    development_platform.REFRESH_COOKIE_SECURE = True
    development_platform.FRONTEND_BASE_URL = "https://localhost:4200"

    assert _ids() == ["plugins.W001"]


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
    development_platform.PLUGINS_BASE_DOMAIN = "plugins.example.com"
    development_platform.PLUGINS_DEV_API_PORT = "abc"

    assert _ids() == []
