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
