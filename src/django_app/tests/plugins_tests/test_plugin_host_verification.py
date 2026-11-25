"""A plugin host must prove it is served by this EpicStaff before EpicStaff sends a login code
there, frames it or approves its plugin.

The proof endpoint is exercised as nginx calls it. Outbound requests are answered at httpx's
transport: either by this deployment (the request is handed to the proof endpoint, as nginx
would) or by a foreign server.
"""

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from plugins.gateway import host_verifier
from plugins.gateway.host_verifier import PluginHostVerifier
from plugins.models import Plugin, PluginState
from rest_framework.test import APIClient

from rbac.models import OrganizationUser

from tests.plugins_tests.conftest import mark_running, upload_file
from tests.plugins_tests.login_helpers import authorize, session_cookie
from tests.plugins_tests.package_builder import build_package

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

PROOF_URL = "/api/plugin-gateway/instance/"
GATEWAY_SECRET = "g" * 32
CHALLENGE = "c" * 43
WEATHER_HOST = "weather-app.example.com"
WEATHER_ORIGIN = f"https://{WEATHER_HOST}"
CACHE_KEY = f"plugins:host-verified:{WEATHER_ORIGIN}"
PROBE_LOCK_KEY = f"{CACHE_KEY}:probing"
FOREIGN_PROOF = "0" * 64
REFUSAL_MESSAGE = f"{WEATHER_HOST} is served by another server, not this EpicStaff: check DNS for that name."


@pytest.fixture
def flat_hosts(plugins_enabled, settings):
    """Plugins beside EpicStaff in its own zone, over HTTPS: hosts that are not .localhost."""
    settings.FRONTEND_BASE_URL = "https://epicstaff.example.com"
    settings.PLUGINS_HOST_TEMPLATE = "{id}-app.example.com"
    settings.PLUGINS_GATEWAY_SECRET = GATEWAY_SECRET
    cache.delete(CACHE_KEY)
    yield
    cache.delete(CACHE_KEY)


def _ask_for_proof(identifier="weather", challenge=CHALLENGE, secret=GATEWAY_SECRET):
    headers = {"HTTP_X_PLUGIN_IDENTIFIER": identifier, "HTTP_X_PLUGIN_HOST_CHALLENGE": challenge}
    if secret is not None:
        headers["HTTP_X_PLUGIN_GATEWAY_SECRET"] = secret
    return APIClient().get(PROOF_URL, **headers)


class _Server:
    """What answers at the plugin host: records each request, answers with `answer`."""

    def __init__(self, answer):
        self.requests: list[httpx.Request] = []
        self._answer = answer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._answer(request)


def _answer(status: int, body: bytes = b"") -> httpx.Response:
    """An answer whose body is read as it arrives, as over the network."""
    return httpx.Response(status, stream=httpx.ByteStream(body))


async def _this_epicstaff(request: httpx.Request) -> httpx.Response:
    """This deployment's nginx: the identifier its server name matches, the challenge, the secret.

    Django is called from a thread of its own, as the probe runs in an event loop."""
    identifier = request.url.host.removesuffix("-app.example.com")
    response = await asyncio.to_thread(
        _ask_for_proof, identifier, request.url.params["challenge"], django_settings.PLUGINS_GATEWAY_SECRET
    )
    return _answer(response.status_code, response.content)


def _foreign_server(request: httpx.Request) -> httpx.Response:
    return _answer(200, json.dumps({"proof": FOREIGN_PROOF}).encode())


@pytest.fixture
def plugin_host(monkeypatch):
    """Route every request the verifier makes to a `_Server` answering with the given function."""

    real_client = httpx.AsyncClient

    def answered_by(answer) -> _Server:
        server = _Server(answer)
        transport = httpx.MockTransport(server)
        monkeypatch.setattr(
            host_verifier.httpx, "AsyncClient", lambda **options: real_client(**{**options, "transport": transport})
        )
        return server

    return answered_by


# ---- the proof endpoint, as nginx calls it ----


def test_the_proof_is_this_deployment_s_hmac_of_the_template_host_and_the_challenge(flat_hosts):
    response = _ask_for_proof()

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json() == {"proof": "8e51542c07faf85a03eacb8e31600d74464cd659ea129b1a952a9cc1dcec9c24"}


def test_a_proof_names_its_host_and_challenge(flat_hosts):
    weather = _ask_for_proof("weather").json()["proof"]

    assert _ask_for_proof("crm").json()["proof"] != weather
    assert _ask_for_proof("weather", "d" * 43).json()["proof"] != weather


@pytest.mark.parametrize("secret", [None, "", "x" * 32])
def test_without_the_gateway_secret_there_is_no_proof(flat_hosts, secret):
    response = _ask_for_proof(secret=secret)

    assert response.status_code == 404
    assert b"proof" not in response.content


@pytest.mark.parametrize("identifier", ["", "Weather", "a" * 33, "weather.example.com"])
def test_an_identifier_the_manifest_does_not_allow_gets_no_proof(flat_hosts, identifier):
    assert _ask_for_proof(identifier).status_code == 404


@pytest.mark.parametrize("challenge", ["", "c" * 42, "c" * 44, "c" * 42 + "=", "c" * 42 + "%"])
def test_a_challenge_that_is_not_43_base64url_characters_is_refused(flat_hosts, challenge):
    response = _ask_for_proof(challenge=challenge)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_challenge"


# ---- the verifier ----


def test_a_host_answering_this_deployment_s_proof_is_served_here(flat_hosts, plugin_host):
    server = plugin_host(_this_epicstaff)

    assert PluginHostVerifier().is_served_here("weather") is True
    [request] = server.requests
    assert (request.method, request.url.host, request.url.path) == ("GET", WEATHER_HOST, "/.well-known/epicstaff/instance")
    assert len(request.url.params["challenge"]) == 43


@pytest.mark.parametrize(
    "answer",
    [
        _foreign_server,
        lambda request: _answer(404),
        lambda request: _answer(200, b"<html>a foreign page</html>"),
        lambda request: _answer(200, b'["not", "an", "object"]'),
        lambda request: _answer(200, b'{"proof": 1}'),
    ],
    ids=["a-foreign-proof", "not-found", "not-json", "not-an-object", "not-a-string"],
)
def test_a_host_without_this_deployment_s_proof_is_not_served_here(flat_hosts, plugin_host, answer):
    plugin_host(answer)

    assert PluginHostVerifier().is_served_here("weather") is False


def test_a_proof_for_another_host_is_not_accepted(flat_hosts, plugin_host):
    async def relays_another_host_s_proof(request):
        response = await asyncio.to_thread(
            _ask_for_proof, "crm", request.url.params["challenge"], django_settings.PLUGINS_GATEWAY_SECRET
        )
        return _answer(200, response.content)

    plugin_host(relays_another_host_s_proof)

    assert PluginHostVerifier().is_served_here("weather") is False


def test_a_host_that_does_not_answer_in_time_is_not_served_here(flat_hosts, plugin_host):
    def times_out(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    plugin_host(times_out)

    assert PluginHostVerifier().is_served_here("weather") is False


def test_a_redirect_is_not_followed(flat_hosts, plugin_host):
    async def redirects_to_a_host_with_the_proof(request):
        if request.url.host == WEATHER_HOST:
            return httpx.Response(
                302,
                headers={"Location": "https://proxy.example.net/.well-known/epicstaff/instance"},
                stream=httpx.ByteStream(b""),
            )
        return await _this_epicstaff(request)

    server = plugin_host(redirects_to_a_host_with_the_proof)

    assert PluginHostVerifier().is_served_here("weather") is False
    assert [request.url.host for request in server.requests] == [WEATHER_HOST]


class _EndlessBody(httpx.AsyncByteStream):
    """A body that never ends: `chunk` every `pause` seconds; counts what was read."""

    def __init__(self, chunk: bytes, pause: float = 0.0):
        self.chunk, self.pause, self.read = chunk, pause, 0

    async def __aiter__(self):
        while True:
            await asyncio.sleep(self.pause)
            self.read += 1
            yield self.chunk


@pytest.fixture
def short_deadline(monkeypatch):
    monkeypatch.setattr(host_verifier, "PROBE_DEADLINE_SECONDS", 0.5)


def test_a_host_dripping_its_answer_is_cut_off_at_the_deadline(flat_hosts, plugin_host, short_deadline):
    plugin_host(lambda request: httpx.Response(200, stream=_EndlessBody(b" ", pause=0.05)))

    started = time.monotonic()
    verified = PluginHostVerifier().is_served_here("weather")

    assert verified is False
    assert time.monotonic() - started < 1.5


def test_a_host_that_never_sends_its_headers_is_cut_off_at_the_deadline(flat_hosts, plugin_host, short_deadline):
    async def never_answers(request):
        await asyncio.sleep(30)

    plugin_host(never_answers)

    started = time.monotonic()
    verified = PluginHostVerifier().is_served_here("weather")

    assert verified is False
    assert time.monotonic() - started < 1.5


def test_a_name_server_that_never_answers_holds_the_caller_only_until_the_deadline(
    flat_hosts, short_deadline, monkeypatch
):
    resolve = socket.getaddrinfo

    def stuck_for_the_plugin_host(host, *arguments, **options):
        if host == WEATHER_HOST:
            time.sleep(3)
        return resolve(host, *arguments, **options)

    monkeypatch.setattr(socket, "getaddrinfo", stuck_for_the_plugin_host)

    started = time.monotonic()
    verified = PluginHostVerifier().is_served_here("weather")

    assert verified is False
    assert time.monotonic() - started < 1.5
    assert cache.get(PROBE_LOCK_KEY) is None


def test_a_probe_lock_that_passed_to_another_probe_is_not_released(flat_hosts, plugin_host):
    def lock_expires_and_another_probe_takes_it(request):
        cache.set(PROBE_LOCK_KEY, "another-probe", 10)
        return _foreign_server(request)

    plugin_host(lock_expires_and_another_probe_takes_it)
    try:
        PluginHostVerifier().is_served_here("weather")

        assert cache.get(PROBE_LOCK_KEY) == "another-probe"
    finally:
        cache.delete(PROBE_LOCK_KEY)


def _probe_threads(plugin_host, count):
    threads = []

    def records_its_thread(request):
        threads.append(threading.get_ident())
        return _foreign_server(request)

    plugin_host(records_its_thread)
    for _ in range(count):
        cache.delete(CACHE_KEY)
        PluginHostVerifier().is_served_here("weather")
    return threads


def test_every_probe_of_a_process_runs_on_one_loop_thread(flat_hosts, plugin_host):
    first, second = _probe_threads(plugin_host, 2)

    assert first == second != threading.get_ident()


def test_a_forked_process_starts_a_loop_thread_of_its_own(flat_hosts, plugin_host, monkeypatch):
    [parent_thread] = _probe_threads(plugin_host, 1)
    monkeypatch.setattr(host_verifier.os, "getpid", lambda: -1)

    [child_thread] = _probe_threads(plugin_host, 1)

    assert child_thread != parent_thread


def test_an_answer_longer_than_a_proof_is_not_read_to_its_end(flat_hosts, plugin_host):
    body = _EndlessBody(b"x" * 512)
    plugin_host(lambda request: httpx.Response(200, stream=body))

    assert PluginHostVerifier().is_served_here("weather") is False
    assert body.read <= 3
    assert 15 < cache.ttl(CACHE_KEY) <= 60


@pytest.mark.parametrize(
    ("answer", "seconds"),
    [
        (_foreign_server, 60),
        (lambda request: _answer(404), 60),
        (lambda request: _answer(200, b"<html>a foreign page</html>"), 60),
        (lambda request: _answer(429), 15),
        (lambda request: _answer(503), 15),
        (lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused", request=request)), 15),
    ],
    ids=["another-server-s-proof", "not-found", "not-json", "throttled", "unavailable", "unreachable"],
)
def test_another_server_s_answer_is_remembered_for_a_minute_and_no_answer_for_moments(
    flat_hosts, plugin_host, answer, seconds
):
    plugin_host(answer)

    assert PluginHostVerifier().is_served_here("weather") is False
    assert seconds - 10 < cache.ttl(CACHE_KEY) <= seconds


def test_no_answer_never_replaces_a_success_another_process_cached(flat_hosts, plugin_host):
    def another_process_succeeds_while_this_one_is_throttled(request):
        cache.set(CACHE_KEY, True, 600)
        return _answer(429)

    plugin_host(another_process_succeeds_while_this_one_is_throttled)

    assert PluginHostVerifier().is_served_here("weather") is False
    assert cache.get(CACHE_KEY) is True


def test_while_another_process_asks_the_host_no_second_request_is_sent(flat_hosts, plugin_host):
    server = plugin_host(_this_epicstaff)
    cache.add(PROBE_LOCK_KEY, 1, 10)
    try:
        verified = PluginHostVerifier().is_served_here("weather")
    finally:
        cache.delete(PROBE_LOCK_KEY)

    assert verified is False
    assert server.requests == []
    assert cache.get(CACHE_KEY) is None


def test_a_success_is_remembered_for_ten_minutes(flat_hosts, plugin_host):
    server = plugin_host(_this_epicstaff)

    PluginHostVerifier().is_served_here("weather")
    PluginHostVerifier().is_served_here("weather")

    assert len(server.requests) == 1
    assert 590 < cache.ttl(CACHE_KEY) <= 600


def test_a_failure_is_remembered_for_a_minute(flat_hosts, plugin_host):
    server = plugin_host(_foreign_server)

    PluginHostVerifier().is_served_here("weather")
    PluginHostVerifier().is_served_here("weather")

    assert len(server.requests) == 1
    assert 50 < cache.ttl(CACHE_KEY) <= 60


def test_localhost_plugin_hosts_are_never_asked(plugin_host):
    server = plugin_host(_foreign_server)

    assert PluginHostVerifier().is_served_here("weather") is True
    assert server.requests == []


@pytest.mark.parametrize("template", ["{id}.plugins.example.com", "{id}.example.com"])
def test_a_template_without_an_affix_is_never_asked(flat_hosts, plugin_host, settings, template):
    settings.PLUGINS_HOST_TEMPLATE = template
    server = plugin_host(_foreign_server)

    assert PluginHostVerifier().is_served_here("weather") is True
    assert server.requests == []


@pytest.mark.parametrize("template", ["{id}-app.example.com", "app-{id}.example.com"])
def test_a_template_with_an_affix_is_asked(flat_hosts, plugin_host, settings, template):
    settings.PLUGINS_HOST_TEMPLATE = template
    server = plugin_host(_foreign_server)

    assert PluginHostVerifier().is_served_here("crm") is False
    assert len(server.requests) == 1


# ---- authorize: no answer ever goes to a host another server holds ----


@pytest.fixture
def weather_in_acme(flat_hosts, plugin_host, backend_plugin, grant_to, acme, settings):
    """Weather installed while its host proved itself, then forgotten: each test decides who
    answers at the host."""
    settings.REFRESH_COOKIE_SECURE = False
    plugin_host(_this_epicstaff)
    plugin = mark_running(backend_plugin())
    grant_to(plugin, acme)
    cache.delete(CACHE_KEY)
    return plugin


@pytest.fixture
def member_of_acme_and_beta(member_only, role_member, beta, weather_in_acme, grant_to):
    grant_to(weather_in_acme, beta)
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


def _assert_answered_on_epicstaff_s_origin(response):
    assert response.status_code == 503
    assert "Location" not in response
    assert response.json()["code"] == "plugin_host_not_served_here"
    assert response.json()["message"] == REFUSAL_MESSAGE


@pytest.mark.parametrize(
    "case",
    ["no-session", "no-session-silent", "a-code", "a-named-organization", "an-organization-not-eligible"],
)
def test_authorize_never_redirects_to_a_host_another_server_holds(
    weather_in_acme, plugin_host, member_only, beta, case
):
    plugin_host(_foreign_server)
    client = APIClient()
    request = {
        "no-session": lambda: authorize(client),
        "no-session-silent": lambda: authorize(client, prompt="none"),
        "a-code": lambda: authorize(client, cookie=session_cookie(member_only)),
        "a-named-organization": lambda: authorize(client, cookie=session_cookie(member_only), org=str(beta.id)),
        "an-organization-not-eligible": lambda: authorize(client, cookie=session_cookie(member_only), org="999999"),
    }[case]

    _assert_answered_on_epicstaff_s_origin(request())


@pytest.mark.parametrize("prompt", [None, "none"])
def test_authorize_with_several_organizations_never_redirects_to_a_foreign_host(
    member_of_acme_and_beta, plugin_host, prompt
):
    plugin_host(_foreign_server)

    response = authorize(APIClient(), cookie=session_cookie(member_of_acme_and_beta), prompt=prompt)

    _assert_answered_on_epicstaff_s_origin(response)


def test_authorize_with_an_affix_less_template_asks_no_host(weather_in_acme, plugin_host, member_only, settings):
    settings.PLUGINS_HOST_TEMPLATE = "{id}.plugins.example.com"
    server = plugin_host(_foreign_server)

    response = authorize(APIClient(), cookie=session_cookie(member_only))

    assert response.status_code == 302
    assert response["Location"].startswith("https://weather.plugins.example.com/.well-known/epicstaff/callback.html#code=")
    assert server.requests == []


def test_authorize_sends_the_code_to_a_host_that_proves_it_is_served_here(weather_in_acme, plugin_host, member_only):
    plugin_host(_this_epicstaff)

    response = authorize(APIClient(), cookie=session_cookie(member_only))

    assert response.status_code == 302
    assert response["Location"].startswith(f"{WEATHER_ORIGIN}/.well-known/epicstaff/callback.html#code=")


# ---- availability ----


def _available(client_as, user, organization):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(organization.id))
    return client.get("/api/plugins/available/")


def test_a_plugin_whose_host_another_server_holds_is_unavailable(client_as, weather_in_acme, plugin_host, member_only, acme):
    plugin_host(_foreign_server)

    response = _available(client_as, member_only, acme)

    assert response.status_code == 200
    [weather] = response.json()
    assert (weather["identifier"], weather["availability"], weather["development"]) == ("weather", "unavailable", False)
    assert weather["frame_origin"] is None


def test_a_plugin_whose_host_proves_itself_is_ready(client_as, weather_in_acme, plugin_host, member_only, acme):
    plugin_host(_this_epicstaff)

    response = _available(client_as, member_only, acme)

    assert [(plugin["identifier"], plugin["availability"], plugin["frame_origin"]) for plugin in response.json()] == [
        ("weather", "ready", WEATHER_ORIGIN)
    ]


def test_a_plugin_in_maintenance_is_not_asked_and_stays_in_maintenance(
    client_as, weather_in_acme, plugin_host, member_only, acme
):
    Plugin.objects.filter(pk=weather_in_acme.pk).update(state=PluginState.MAINTENANCE)
    server = plugin_host(_foreign_server)

    response = _available(client_as, member_only, acme)

    assert [plugin["availability"] for plugin in response.json()] == ["maintenance"]
    assert server.requests == []


# ---- review and approval ----


def _upload(client):
    return client.post("/api/admin/plugins/packages/", {"file": upload_file(build_package())}, format="multipart")


def test_approving_a_plugin_whose_host_another_server_holds_is_refused(flat_hosts, plugin_host, superadmin_client):
    plugin_host(_foreign_server)
    review = _upload(superadmin_client).json()

    response = superadmin_client.post(
        f"/api/admin/plugins/packages/{review['id']}/approve/", {"untrusted_acknowledged": True}, format="json"
    )

    assert response.status_code == 503
    assert response.json()["code"] == "plugin_host_not_served_here"
    assert response.json()["message"] == REFUSAL_MESSAGE
    assert Plugin.objects.get(identifier="weather").current_package is None


def test_the_review_warns_that_another_server_holds_the_plugin_s_host(flat_hosts, plugin_host, superadmin_client):
    plugin_host(_foreign_server)

    review = _upload(superadmin_client).json()

    assert {"code": "host_not_served_here", "message": REFUSAL_MESSAGE} in review["warnings"]


def test_the_review_has_no_host_warning_when_the_host_proves_itself(flat_hosts, plugin_host, superadmin_client):
    plugin_host(_this_epicstaff)

    review = _upload(superadmin_client).json()

    assert "host_not_served_here" not in [warning["code"] for warning in review["warnings"]]
