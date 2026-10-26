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
    origins = PluginOrigins(frontend_base_url, "plugins.example.localhost")

    assert origins.epicstaff_origin == epicstaff_origin
    assert origins.frame_origin("weather") == frame_origin
    assert origins.plugin_host("weather") == "weather.plugins.example.localhost"


ORIGINS = PluginOrigins("http://epicstaff.localhost", "plugins.epicstaff.localhost")


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
    origins = PluginOrigins("https://epicstaff.example.com:8443", "plugins.example.com")

    assert origins.identifier_from_origin(origins.frame_origin("weather")) == "weather"
    assert origins.identifier_from_origin("https://weather.plugins.example.com") is None


@pytest.mark.parametrize(
    ("origin", "in_plugin_domain"),
    [
        ("http://weather.plugins.epicstaff.localhost", True),
        ("https://weather.plugins.epicstaff.localhost:8443", True),
        ("http://a.b.plugins.epicstaff.localhost", True),
        ("http://plugins.epicstaff.localhost", True),
        ("http://WEATHER.Plugins.epicstaff.localhost", True),
        ("http://weather.plugins.epicstaff.localhost.", True),
        ("http://epicstaff.localhost", False),
        ("http://xplugins.epicstaff.localhost", False),
        ("http://weather.plugins.epicstaff.localhost.evil.test", False),
        ("null", False),
        ("http://[::1", False),
        ("", False),
    ],
)
def test_the_plugin_domain_is_the_base_domain_and_every_host_under_it(origin, in_plugin_domain):
    assert ORIGINS.is_plugin_domain_origin(origin) is in_plugin_domain
