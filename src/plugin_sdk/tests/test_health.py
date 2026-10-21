import pytest

from asgi_client import request
from epicstaff_plugin.health import HealthCheckMiddleware
from epicstaff_plugin.serve import build_app


async def plugin_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def test_the_health_endpoint_answers_without_a_context(runtime):
    response = request(build_app(plugin_app, runtime), "GET", "/_epicstaff/health")

    assert (response.status, response.json()) == (200, {"status": "ok"})


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/_epicstaff/health"), ("GET", "/_epicstaff/health/"), ("GET", "/_epicstaff/hooks/install")],
)
def test_nothing_else_under_epicstaff_skips_the_context_check(runtime, method, path):
    assert request(build_app(plugin_app, runtime), method, path).status == 401


def test_every_other_request_goes_to_the_app():
    assert request(HealthCheckMiddleware(plugin_app), "GET", "/api/ping").status == 204
