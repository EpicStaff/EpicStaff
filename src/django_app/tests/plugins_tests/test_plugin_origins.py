import pytest
from plugins.origins import PluginOrigins


@pytest.mark.parametrize(
    ("frontend_base_url", "epicstaff_origin", "frame_origin"),
    [
        ("http://epicstaff.localhost", "http://epicstaff.localhost", "http://weather.plugins.example.localhost"),
        ("https://EpicStaff.example.com", "https://epicstaff.example.com", "https://weather.plugins.example.localhost"),
        ("https://epicstaff.example.com:8443", "https://epicstaff.example.com:8443", "https://weather.plugins.example.localhost:8443"),
        ("https://epicstaff.example.com:443", "https://epicstaff.example.com", "https://weather.plugins.example.localhost"),
        ("http://epicstaff.localhost:80/", "http://epicstaff.localhost", "http://weather.plugins.example.localhost"),
    ],
)
def test_origins_take_epicstaff_s_scheme_and_explicit_port(frontend_base_url, epicstaff_origin, frame_origin):
    origins = PluginOrigins(frontend_base_url, "{id}.plugins.example.localhost")

    assert origins.epicstaff_origin == epicstaff_origin
    assert origins.frame_origin("weather") == frame_origin
    assert origins.plugin_host("weather") == "weather.plugins.example.localhost"


ORIGINS = PluginOrigins("http://epicstaff.localhost", "{id}.plugins.epicstaff.localhost")


@pytest.mark.parametrize(
    ("origin", "identifier"),
    [
        ("http://weather.plugins.epicstaff.localhost", "weather"),
        ("http://my-plugin2.plugins.epicstaff.localhost", "my-plugin2"),
        ("https://weather.plugins.epicstaff.localhost", None),
        ("http://weather.plugins.epicstaff.localhost:8080", None),
        ("http://a.weather.plugins.epicstaff.localhost", None),
        ("http://plugins.epicstaff.localhost", None),
        ("http://WEATHER.plugins.epicstaff.localhost", None),
        ("http://weather.plugins.epicstaff.localhost/", None),
        ("http://-weather.plugins.epicstaff.localhost", None),
        ("http://weather.xplugins.epicstaff.localhost", None),
        ("http://epicstaff.localhost", None),
        ("null", None),
    ],
)
def test_only_an_exact_plugin_frame_origin_names_a_plugin(origin, identifier):
    assert ORIGINS.identifier_from_origin(origin) == identifier


def test_the_frame_origin_of_an_identifier_names_it_with_an_explicit_port():
    origins = PluginOrigins("https://epicstaff.example.com:8443", "{id}.plugins.example.com")

    assert origins.identifier_from_origin(origins.frame_origin("weather")) == "weather"
    assert origins.identifier_from_origin("https://weather.plugins.example.com") is None


@pytest.mark.parametrize(
    ("origin", "in_plugin_zone"),
    [
        ("http://weather.plugins.epicstaff.localhost", True),
        ("https://weather.plugins.epicstaff.localhost:8443", True),
        ("http://a.b.plugins.epicstaff.localhost", True),
        ("http://plugins.epicstaff.localhost", True),
        ("http://WEATHER.Plugins.epicstaff.localhost", True),
        ("http://weather.plugins.epicstaff.localhost.", True),
        ("http://.plugins.epicstaff.localhost", True),
        ("http://a..plugins.epicstaff.localhost", True),
        ("http://..plugins.epicstaff.localhost", True),
        ("http://epicstaff.localhost", False),
        ("http://xplugins.epicstaff.localhost", False),
        ("http://weather.plugins.epicstaff.localhost.evil.test", False),
        ("null", False),
        ("http://[::1", False),
        ("", False),
    ],
)
def test_without_an_affix_the_plugin_zone_is_the_parent_and_every_host_under_it(origin, in_plugin_zone):
    assert ORIGINS.is_plugin_zone_origin(origin) is in_plugin_zone


FLAT = PluginOrigins("https://epicstaff.example.com", "{id}-app.example.com")
PREFIXED = PluginOrigins("https://epicstaff.example.com", "app-{id}.example.com")


def test_a_flat_template_names_the_plugin_host_beside_epicstaff():
    assert FLAT.plugin_host("weather") == "weather-app.example.com"
    assert FLAT.frame_origin("weather") == "https://weather-app.example.com"
    assert PREFIXED.frame_origin("weather") == "https://app-weather.example.com"


@pytest.mark.parametrize(
    ("origins", "origin", "identifier"),
    [
        (FLAT, "https://weather-app.example.com", "weather"),
        (FLAT, "https://my-app-app.example.com", "my-app"),
        (FLAT, "https://-app.example.com", None),
        (FLAT, "https://w-app.example.com", None),
        (FLAT, "https://weather.example.com", None),
        (FLAT, "https://weather-app.example.com:8443", None),
        (FLAT, "http://weather-app.example.com", None),
        (FLAT, "https://a.weather-app.example.com", None),
        (FLAT, "https://weather-apps.example.com", None),
        (FLAT, "https://Weather-app.example.com", None),
        (FLAT, "https://epicstaff.example.com", None),
        (PREFIXED, "https://app-weather.example.com", "weather"),
        (PREFIXED, "https://app-.example.com", None),
        (PREFIXED, "https://weather-app.example.com", None),
    ],
)
def test_with_an_affix_only_the_affixes_around_a_valid_identifier_name_a_plugin(origins, origin, identifier):
    assert origins.identifier_from_origin(origin) == identifier


@pytest.mark.parametrize(
    ("origins", "origin", "in_plugin_zone"),
    [
        (FLAT, "https://weather-app.example.com", True),
        (FLAT, "http://weather-app.example.com:8080", True),
        (FLAT, "https://WEATHER-APP.Example.com.", True),
        (FLAT, "https://a.b.weather-app.example.com", True),
        (FLAT, "https://w-app.example.com", True),
        (FLAT, "https://x_y-app.example.com", True),
        (FLAT, "https://-app.example.com", False),
        (FLAT, "https://example.com", False),
        (FLAT, "https://epicstaff.example.com", False),
        (FLAT, "https://app.example.com", False),
        (FLAT, "https://weather-apps.example.com", False),
        (FLAT, "https://weather-app.example.com.evil.test", False),
        (FLAT, "https://weather-app.other.example.com", False),
        (PREFIXED, "https://app-weather.example.com", True),
        (PREFIXED, "https://deep.app-x.example.com", True),
        (PREFIXED, "https://weather-app.example.com", False),
        (PREFIXED, "https://example.com", False),
    ],
)
def test_with_an_affix_the_plugin_zone_is_every_host_of_the_plugin_shape_and_under_it(origins, origin, in_plugin_zone):
    assert origins.is_plugin_zone_origin(origin) is in_plugin_zone
