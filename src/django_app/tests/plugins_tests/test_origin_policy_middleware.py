"""A plugin page may ask EpicStaff for the token exchange and the authorize navigation, nothing else."""

import asyncio
import json
from urllib.parse import urlencode

import pytest
from django.conf import settings as django_settings
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse
from loguru import logger as loguru_logger
from plugins.gateway.origin_policy_middleware import PASSWORD_CHANGE_CONFIRM_PATH, PluginOriginPolicyMiddleware
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from tests.plugins_tests.login_helpers import AUTHORIZE_URL, EPICSTAFF_ORIGIN, TOKEN_URL, WEATHER_ORIGIN, authorize, session_cookie

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("login_platform")]

REFUSAL = {
    "status_code": 403,
    "code": "plugin_origin_refused",
    "message": "Plugin pages cannot call EpicStaff's API.",
}


@pytest.fixture
def plugin_page():
    """A client whose every request comes from the Weather plugin's page."""
    client = APIClient()
    client.credentials(HTTP_ORIGIN=WEATHER_ORIGIN)
    return client


@pytest.fixture
def log_messages():
    messages = []
    sink_id = loguru_logger.add(lambda message: messages.append(message.record["message"]), level="INFO")
    yield messages
    loguru_logger.remove(sink_id)


def _assert_refused(response):
    assert response.status_code == 403
    assert response.json() == REFUSAL
    assert "Access-Control-Allow-Credentials" not in response.headers
    assert "Access-Control-Allow-Origin" not in response.headers


# ---- everything else is refused before any view runs ----


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/auth/refresh/"),
        ("post", "/api/auth/logout/"),
        ("post", "/api/auth/login/"),
        ("get", "/api/profile/api-keys/"),
        ("get", "/api/graphs/"),
        ("get", "/api/plugins/available/"),
        ("post", AUTHORIZE_URL),
        ("get", TOKEN_URL),
        ("get", "/api/plugin-public/weather/config/"),
    ],
)
def test_a_plugin_page_is_refused_everywhere_else(plugin_page, method, path):
    _assert_refused(getattr(plugin_page, method)(path))


def test_a_preflight_to_any_other_path_is_refused(plugin_page):
    response = plugin_page.options(
        "/api/graphs/", HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET", HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization"
    )

    _assert_refused(response)


@pytest.mark.parametrize(
    ("request_method", "request_headers"),
    [("PUT", "content-type"), ("POST", "content-type, authorization"), ("POST", "x-organization-id")],
)
def test_a_token_preflight_asking_for_more_than_a_json_post_is_refused(plugin_page, request_method, request_headers):
    response = plugin_page.options(
        TOKEN_URL,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD=request_method,
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS=request_headers,
    )

    _assert_refused(response)


def test_the_view_never_runs_on_a_refusal(regular_user, jwt_tokens):
    client = APIClient()
    client.credentials(HTTP_ORIGIN=WEATHER_ORIGIN, HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")

    response = client.post("/api/auth/logout/", HTTP_COOKIE=f"auth.refresh={jwt_tokens['refresh']}")

    _assert_refused(response)
    assert not BlacklistedToken.objects.exists()
    assert not response.cookies
    still_logged_in = APIClient().post("/api/auth/refresh/", HTTP_COOKIE=f"auth.refresh={jwt_tokens['refresh']}")
    assert still_logged_in.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://a.weather.plugins.epicstaff.localhost",
        "http://plugins.epicstaff.localhost",
        "http://WEATHER.plugins.epicstaff.localhost",
        "http://weather.plugins.epicstaff.localhost.",
        "http://weather.plugins.epicstaff.localhost:8080",
        "https://weather.plugins.epicstaff.localhost",
    ],
    ids=["nested-label", "base-domain", "upper-case-host", "trailing-dot", "other-port", "other-scheme"],
)
def test_a_plugin_domain_origin_that_is_not_an_exact_plugin_origin_cannot_exchange(origin):
    client = APIClient()

    response = client.post(TOKEN_URL, {}, format="json", HTTP_ORIGIN=origin)

    _assert_refused(response)


def test_an_http_plugin_origin_on_an_https_deployment_is_refused(settings):
    settings.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    settings.PLUGINS_BASE_DOMAIN = "plugins.example.com"

    plain = APIClient().post(TOKEN_URL, {}, format="json", HTTP_ORIGIN="http://weather.plugins.example.com")
    secure = APIClient().post(TOKEN_URL, {}, format="json", HTTP_ORIGIN="https://weather.plugins.example.com")

    _assert_refused(plain)
    assert secure.status_code == 400


# ---- what a plugin page may do ----


def test_the_token_exchange_from_the_exact_plugin_origin_reaches_the_view(plugin_page):
    response = plugin_page.post(TOKEN_URL, {}, format="json")

    assert (response.status_code, response.json()["code"]) == (400, "invalid")
    assert response["Access-Control-Allow-Origin"] == WEATHER_ORIGIN


def test_the_authorize_navigation_passes_without_cors_headers(plugin_page, settings, member_only, loginable_weather, grant_to, acme):
    grant_to(loginable_weather, acme)
    settings.CORS_ALLOWED_ORIGINS = [*(settings.CORS_ALLOWED_ORIGINS or []), WEATHER_ORIGIN]

    response = authorize(plugin_page, cookie=session_cookie(member_only))

    assert response.status_code == 302
    assert not [name for name in response.headers if name.lower().startswith("access-control-")]


# ---- other origins are not the policy's business ----


def test_epicstaff_s_own_origin_is_unaffected():
    response = APIClient().get("/api/graphs/", HTTP_ORIGIN=EPICSTAFF_ORIGIN)

    assert response.status_code == 401


def test_an_allow_listed_cors_origin_keeps_its_credentials(settings):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:4200"]

    response = APIClient().get("/api/graphs/", HTTP_ORIGIN="http://localhost:4200")

    assert response.status_code == 401
    assert response["Access-Control-Allow-Origin"] == "http://localhost:4200"
    assert response["Access-Control-Allow-Credentials"] == "true"


@pytest.mark.parametrize("origin", ["null", "http://[::1", "not an origin"])
def test_a_null_or_unparsable_origin_is_no_plugin_origin_on_a_bearer_endpoint(origin):
    assert APIClient().get("/api/graphs/", HTTP_ORIGIN=origin).status_code == 401


# ---- a hidden origin (`Origin: null`) cannot touch the refresh cookie ----


def _json(body):
    return {"data": json.dumps(body), "content_type": "application/json"}


def _form(body):
    return {"data": urlencode(body), "content_type": "application/x-www-form-urlencoded"}


def _text(body):
    return {"data": json.dumps(body), "content_type": "text/plain"}


BODY_KINDS = [_json, _form, _text]
BODY_IDS = ["json", "form", "text-plain"]


@pytest.mark.parametrize("encode", BODY_KINDS, ids=BODY_IDS)
@pytest.mark.parametrize("origin", ["null", "NULL", "Null"])
def test_a_null_origin_cannot_log_in(regular_user, encode, origin):
    tokens_before = OutstandingToken.objects.count()

    response = APIClient().post(
        "/api/auth/login/",
        **encode({"email": regular_user.email, "password": "UserStrongPass123!"}),
        HTTP_ORIGIN=origin,
    )

    _assert_refused(response)
    assert not response.cookies
    assert OutstandingToken.objects.count() == tokens_before


@pytest.mark.parametrize("encode", BODY_KINDS, ids=BODY_IDS)
def test_a_null_origin_cannot_log_out(jwt_tokens, encode):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}", HTTP_ORIGIN="null")

    response = client.post("/api/auth/logout/", **encode({}), HTTP_COOKIE=f"auth.refresh={jwt_tokens['refresh']}")

    _assert_refused(response)
    assert not BlacklistedToken.objects.exists()
    assert APIClient().post("/api/auth/refresh/", HTTP_COOKIE=f"auth.refresh={jwt_tokens['refresh']}").status_code == 200


@pytest.mark.parametrize("encode", BODY_KINDS, ids=BODY_IDS)
def test_a_null_origin_cannot_refresh(jwt_tokens, encode):
    response = APIClient().post(
        "/api/auth/refresh/", **encode({}), HTTP_ORIGIN="null", HTTP_COOKIE=f"auth.refresh={jwt_tokens['refresh']}"
    )

    _assert_refused(response)
    assert not response.cookies
    # Not rotated: rotation would have blacklisted the token this request carried.
    assert not BlacklistedToken.objects.exists()


def test_a_null_origin_cannot_confirm_a_password_change(member_only):
    client = APIClient()
    client.force_authenticate(user=member_only)
    ticket = client.post(
        reverse("profile_password_change_request"), {"current_password": "StrongPass123!"}, format="json"
    ).json()["ticket"]
    password_before = member_only.password

    response = client.post(
        reverse("profile_password_change_confirm"),
        {"ticket": ticket, "new_password": "BrandNewPass456!"},
        format="json",
        HTTP_ORIGIN="null",
    )

    _assert_refused(response)
    member_only.refresh_from_db()
    assert member_only.password == password_before


def test_the_password_change_confirm_path_is_the_one_rbac_routes():
    assert reverse("profile_password_change_confirm") == PASSWORD_CHANGE_CONFIRM_PATH


def test_a_null_origin_may_still_navigate_to_authorize(member_only, loginable_weather, grant_to, acme):
    grant_to(loginable_weather, acme)
    client = APIClient()
    client.credentials(HTTP_ORIGIN="null")

    assert authorize(client, cookie=session_cookie(member_only)).status_code == 302


def test_a_null_origin_preflight_is_left_to_corsheaders():
    response = APIClient().options(
        "/api/auth/login/", HTTP_ORIGIN="null", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST"
    )

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_a_null_origin_is_not_refused_on_a_bearer_endpoint(jwt_tokens):
    # A page with a hidden origin cannot send Authorization without a preflight that `null`
    # never passes, so a request with a valid bearer here was not made by such a page.
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}", HTTP_ORIGIN="null")

    response = client.post("/api/graphs/", {}, format="json")

    assert response.json().get("code") != "plugin_origin_refused"
    assert APIClient().post("/api/graphs/", {}, format="json", HTTP_ORIGIN="null").status_code == 401


def test_a_null_origin_is_left_alone_while_the_platform_is_off(settings, regular_user):
    settings.PLUGINS_ENABLED = False

    response = APIClient().post(
        "/api/auth/login/",
        **_json({"email": regular_user.email, "password": "UserStrongPass123!"}),
        HTTP_ORIGIN="null",
    )

    assert response.status_code == 200


def test_a_null_origin_refusal_is_logged_without_the_credentials(regular_user, log_messages):
    APIClient().post(
        "/api/auth/login/",
        **_json({"email": regular_user.email, "password": "UserStrongPass123!"}),
        HTTP_ORIGIN="null",
    )

    [line] = [message for message in log_messages if message.startswith("plugins.origin_refused")]
    assert line == "plugins.origin_refused origin='null' method='POST' path='/api/auth/login/'"
    assert "UserStrongPass123!" not in line


def test_the_policy_is_inert_while_the_platform_is_off(settings):
    settings.PLUGINS_ENABLED = False

    response = APIClient().post("/api/auth/refresh/", HTTP_ORIGIN=WEATHER_ORIGIN)

    assert response.status_code == 401
    assert response.json() == {"detail": "No refresh token."}


# ---- placement, async requests and the log ----


def test_the_policy_runs_immediately_before_corsheaders():
    middleware = django_settings.MIDDLEWARE
    policy = middleware.index("plugins.gateway.origin_policy_middleware.PluginOriginPolicyMiddleware")

    assert middleware[policy + 1] == "corsheaders.middleware.CorsMiddleware"


def test_the_policy_works_in_an_async_middleware_chain():
    async def view(request):
        return HttpResponse("view ran")

    middleware = PluginOriginPolicyMiddleware(view)
    factory = RequestFactory()

    refused = asyncio.run(middleware(factory.get("/api/graphs/", HTTP_ORIGIN=WEATHER_ORIGIN)))
    passed = asyncio.run(middleware(factory.get("/api/graphs/", HTTP_ORIGIN=EPICSTAFF_ORIGIN)))
    exchanged = asyncio.run(middleware(factory.post(TOKEN_URL, HTTP_ORIGIN=WEATHER_ORIGIN)))

    assert refused.status_code == 403
    assert passed.content == b"view ran"
    assert exchanged["Access-Control-Allow-Origin"] == WEATHER_ORIGIN


def test_a_refusal_is_logged_without_any_secret(plugin_page, log_messages, regular_user):
    refresh = str(RefreshToken.for_user(regular_user))
    plugin_page.credentials(HTTP_ORIGIN=WEATHER_ORIGIN, HTTP_AUTHORIZATION="Bearer secret-bearer-value")

    plugin_page.post(
        "/api/auth/refresh/?state=secret-state-value&code=secret-code-value",
        HTTP_COOKIE=f"auth.refresh={refresh}",
    )

    [line] = [message for message in log_messages if message.startswith("plugins.origin_refused")]
    assert line == f"plugins.origin_refused origin='{WEATHER_ORIGIN}' method='POST' path='/api/auth/refresh/'"
    for secret in (refresh, "secret-bearer-value", "secret-state-value", "secret-code-value"):
        assert secret not in line
