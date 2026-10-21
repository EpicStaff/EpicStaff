import asyncio
import base64
import importlib
import io
import json
import re
import tomllib
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from packaging.requirements import Requirement

from asgi_client import request
from conftest import REPO_ROOT
from epicstaff_plugin.client import EpicStaffClient
from epicstaff_plugin.package_source import collect_source
from epicstaff_plugin.requirements_lock import parse_requirements_lock
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import HookSigner, service_account_key, write_runtime_file
from fake_epicstaff import FakeEpicStaff
from fake_weather_stores import FakeForecastRuns, FakePopupRelay, FakeSavedPlaces
from local_servers import EmptyApi, RefusingProxy, serving

SAMPLE = REPO_ROOT / "plugin-samples" / "weather"
SDK_PYPROJECT = REPO_ROOT / "src" / "plugin_sdk" / "pyproject.toml"
LOGIN_PROTOCOL = REPO_ROOT / "plugin-sdk" / "contracts" / "login-protocol.json"

ADA = {"id": 42, "email": "ada@acme.test", "name": "Ada"}
EVE = {"id": 43, "email": "eve@acme.test", "name": "Eve"}
OLGA = {"id": 44, "email": "olga@acme.test", "name": "Olga"}
ACME_KEY = service_account_key()
ACME = {"id": 3, "name": "Acme"}
CONTOSO = {"id": 5, "name": "Contoso"}
# A popup state made for Acme (org 3), as the JS SDK's createPopupState makes it.
ACME_STATE = "3.k3Jq9_x-Lm2Np4Qr6St8Uv"
INVALID_REQUEST = (400, {"code": "invalid_request"})
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
# What Open-Meteo's geocoding API answers, trimmed: the second result has no country.
LISBON_ANSWER = {
    "results": [
        {"id": 2267057, "name": "Lisbon", "latitude": 38.71667, "longitude": -9.13333, "country_code": "PT", "country": "Portugal", "admin1": "Lisbon"},
        {"id": 9999001, "name": "Lisbon Seamount", "latitude": 37.5, "longitude": -11.0},
        {"id": 4964811, "name": "Lisbon", "latitude": 44.03, "longitude": -70.1, "country": "United States", "admin1": "Maine"},
    ],
    "generationtime_ms": 0.6,
}
LISBON = {"name": "Lisbon", "country": "Portugal", "admin1": "Lisbon", "latitude": 38.71667, "longitude": -9.13333}


@pytest.fixture
def sample_modules(monkeypatch):
    """The sample backend's modules, imported from its source directory."""
    monkeypatch.syspath_prepend(str(SAMPLE / "backend" / "src"))
    return SimpleNamespace(
        app=importlib.import_module("weather_plugin.app"),
        places=importlib.import_module("weather_plugin.places"),
        place_search=importlib.import_module("weather_plugin.place_search"),
        popup_relay=importlib.import_module("weather_plugin.popup_relay"),
    )


@pytest.fixture
def epicstaff_api():
    """EpicStaff's API as the sample sees it, for organization 3 (Acme)."""
    return FakeEpicStaff(org_id=ACME["id"])


@pytest.fixture
def stores(sample_modules):
    """In-memory stand-ins for the sample's database stores, empty in every test."""
    return SimpleNamespace(
        places=FakeSavedPlaces(sample_modules.places),
        forecast_runs=FakeForecastRuns(),
        popup_relay=FakePopupRelay(),
    )


class FakeGeocoding:
    """Open-Meteo's geocoding API: records every request and answers `answer` (or raises it)."""

    def __init__(self):
        self.requests = []
        self.answer = httpx.Response(200, json=LISBON_ANSWER)

    def __call__(self, request):
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def geocoding():
    return FakeGeocoding()


def _serve_with(monkeypatch, app_module, runtime, epicstaff, stores, place_search):
    for name, value in {
        "places": stores.places,
        "forecast_runs": stores.forecast_runs,
        "popup_relay": stores.popup_relay,
        "place_search": place_search,
        "epicstaff": epicstaff,
    }.items():
        # The lifespan sets the stores; tests that do not run it set them here.
        monkeypatch.setattr(app_module.app.state, name, value, raising=False)
    return build_app(app_module.app, runtime, epicstaff=epicstaff)


@pytest.fixture
def weather(monkeypatch, tmp_path, signer, sample_modules, epicstaff_api, stores, geocoding):
    """The sample's app, served as the node serves it, with `units` set to imperial.

    It holds a service account for Acme and calls `epicstaff_api`. Its stores are `stores`,
    and its place search calls `geocoding`.
    """
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(
        runtime_file,
        signer=signer,
        settings={"units": "imperial"},
        secret_settings={"forecast_api_token": "s3cret-token"},
        service_accounts={"3": {"key": ACME_KEY, "org_name": "Acme", "grant_state": "active"}},
    )
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    runtime = RuntimeConfig.load(runtime_file)
    epicstaff = EpicStaffClient(runtime, transport=epicstaff_api.transport())
    place_search = sample_modules.place_search.PlaceSearch(transport=httpx.MockTransport(geocoding))
    return _serve_with(monkeypatch, sample_modules.app, runtime, epicstaff, stores, place_search)


def _as_person(signer, method, path, person=ADA, org=ACME):
    return signer.headers(method, path, mode="user", user=person, org=org)


def _post_result(weather, signer, body, *, person=ADA, org=ACME, content_type="application/json"):
    headers = {**_as_person(signer, "POST", "/api/popup-relay", person, org), "content-type": content_type}
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return request(weather, "POST", "/api/popup-relay", headers, raw)


def _poll(weather, signer, state=ACME_STATE, *, person=ADA, org=ACME):
    path = f"/api/popup-relay/{state}"
    return request(weather, "GET", path, _as_person(signer, "GET", path, person, org))


def _demo_provider(weather, signer, query):
    return request(weather, "GET", "/api/demo-provider", signer.headers("GET", "/api/demo-provider"), query=query)


def test_ping_answers_a_public_context(weather, signer):
    response = request(weather, "GET", "/api/ping", signer.headers("GET", "/api/ping"))

    assert (response.status, response.json()) == (200, {"status": "ok", "mode": "public"})


def test_ping_without_a_context_is_refused(weather):
    response = request(weather, "GET", "/api/ping")

    assert (response.status, response.json()) == (401, {"code": "context_invalid"})


def test_ping_with_a_context_for_another_path_is_refused(weather, signer):
    assert request(weather, "GET", "/api/ping", signer.headers("GET", "/api/whoami")).status == 401


def test_whoami_answers_who_is_asking_from_the_user_context(weather, signer):
    response = request(weather, "GET", "/api/whoami", _as_person(signer, "GET", "/api/whoami"))

    assert response.status == 200
    assert response.json() == {
        "mode": "user",
        "user": ADA,
        "org": ACME,
        "permissions": ["read"],
        "request": {"method": "GET", "path": "/api/whoami"},
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/whoami"), ("POST", "/api/popup-relay"), ("GET", f"/api/popup-relay/{ACME_STATE}")],
)
def test_a_route_for_people_refuses_a_public_context(weather, signer, method, path):
    response = request(weather, method, path, signer.headers(method, path))

    assert (response.status, response.json()) == (401, {"code": "login_required"})


def test_settings_shows_the_units_and_never_the_secret(weather, signer):
    response = request(weather, "GET", "/api/settings", signer.headers("GET", "/api/settings"))

    assert response.json() == {"units": "imperial"}
    assert b"s3cret-token" not in response.body


def test_the_sample_has_no_generated_api_pages(weather, signer):
    for path in ("/docs", "/openapi.json"):
        assert request(weather, "GET", path, signer.headers("GET", path)).status == 404


def test_the_sample_source_is_a_valid_backend_plugin():
    source = collect_source(SAMPLE, None)
    contents = source.describe()

    assert source.problems(contents, require_sdk_pin=False) == []
    assert source.manifest.version == "0.5.0"
    assert source.manifest.hooks.install
    assert source.manifest.database is not None
    assert [path for path in contents if path.startswith("database/")] == ["database/migrations/001_weather.sql"]
    assert [(host.host, host.reason) for host in source.manifest.outbound_hosts] == [
        ("geocoding-api.open-meteo.com", "Looks up places by name when someone adds a saved place.")
    ]
    assert source.manifest.limits.model_dump(exclude_none=True) == {
        "memory_mb": 256,
        "db_connections": 3,
        "statement_timeout_seconds": 10,
    }
    assert {declaration.resource_type: declaration.actions for declaration in source.manifest.access} == {
        "flows": ["read", "create", "update", "use"],
        "files": ["read", "create"],
        "secrets": ["read", "create", "use"],
        "llm_configs": ["read", "create"],
    }
    assert source.manifest.user_permission_defaults("org_admin") == ["read", "update", "delete"]
    assert source.manifest.user_permission_defaults("member") == ["read", "update"]
    assert source.manifest.user_permission_defaults("viewer") == []
    assert [public_path.model_dump(mode="json") for public_path in source.manifest.public_paths] == [
        {"path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0},
        {
            "path": "/api/demo-provider",
            "match": "exact",
            "methods": ["GET"],
            "rate_limit_per_minute": 30,
            "max_body_kb": 0,
        },
    ]


def test_the_sample_lock_pins_every_requirement_of_the_sdk():
    # The SDK wheel is added by `pack --local-wheel`; its requirements must already be in the
    # lock, or the node's offline install fails.
    lock = parse_requirements_lock((SAMPLE / "backend" / "requirements.lock").read_bytes())
    sdk_requirements = tomllib.loads(SDK_PYPROJECT.read_text())["project"]["dependencies"]

    for text in sdk_requirements:
        requirement = Requirement(text)
        pins = lock.pins(requirement.name)
        assert pins, f"the sample lock does not pin {requirement.name}"
        assert all(requirement.specifier.contains(pin.version) for pin in pins), text


# --- The demo OAuth provider (a public path) ---

REDIRECT_PAGE = re.compile(
    r'<!doctype html><meta http-equiv="refresh" '
    r'content="0;url=/oauth-demo/callback\?code=demo-[0-9a-f]{16}&amp;state=' + re.escape(ACME_STATE) + r'">'
)


def test_the_demo_provider_redirects_to_the_callback_with_a_code_and_the_state(weather, signer):
    response = _demo_provider(weather, signer, f"state={ACME_STATE}&coop=0")

    assert response.status == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert REDIRECT_PAGE.fullmatch(response.body.decode())
    assert "cross-origin-opener-policy" not in response.headers


def test_the_demo_provider_severs_the_opener_only_with_coop_1(weather, signer):
    response = _demo_provider(weather, signer, f"state={ACME_STATE}&coop=1")

    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert REDIRECT_PAGE.fullmatch(response.body.decode())


def test_the_demo_provider_html_escapes_the_target_address(weather, signer):
    body = _demo_provider(weather, signer, f"state={ACME_STATE}&coop=0").body.decode()

    assert "&amp;state=" in body
    assert "&state=" not in body


def test_the_demo_provider_issues_a_new_code_every_time(weather, signer):
    first, second = (_demo_provider(weather, signer, f"state={ACME_STATE}&coop=0").body for _ in range(2))

    assert first != second


@pytest.mark.parametrize(
    "query",
    [
        "",
        "coop=0",
        f"state={ACME_STATE}",
        f"state={ACME_STATE}&coop=2",
        f"state={ACME_STATE}&coop=true",
        f"state={ACME_STATE}&coop=",
        "state=0.k3Jq9_x-Lm2Np4Qr6St8Uv&coop=0",
        "state=03.k3Jq9_x-Lm2Np4Qr6St8Uv&coop=0",
        "state=3.k3Jq9_x-Lm2Np4Qr6St8U&coop=0",
        f"state=3.{'a' * 65}&coop=0",
        "state=12345678901.k3Jq9_x-Lm2Np4Qr6St8Uv&coop=0",
        "state=k3Jq9_x-Lm2Np4Qr6St8Uv&coop=0",
        f"state={ACME_STATE}%0A&coop=0",
        "state=3.k3Jq9_x-Lm2Np4Qr6St8Uv%22%3E%3Cscript%3E&coop=0",
        f"state={ACME_STATE}&state={ACME_STATE}&coop=0",
        f"state={ACME_STATE}&coop=0&coop=1",
        f"state={ACME_STATE}&coop=0&redirect_uri=https://evil.example",
    ],
    ids=[
        "nothing",
        "no state",
        "no coop",
        "coop 2",
        "coop true",
        "coop empty",
        "org 0",
        "leading zero",
        "random part too short",
        "random part too long",
        "org id too long",
        "no org id",
        "trailing newline",
        "markup",
        "repeated state",
        "repeated coop",
        "unknown parameter",
    ],
)
def test_the_demo_provider_refuses_any_other_query(weather, signer, query):
    response = _demo_provider(weather, signer, query)

    assert (response.status, response.json()) == INVALID_REQUEST


# --- The popup relay (for people only) ---


def test_the_person_who_posted_a_result_gets_it_once(weather, signer):
    posted = _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "demo-0123", "state": ACME_STATE}})

    assert (posted.status, posted.body) == (204, b"")
    first = _poll(weather, signer)
    assert (first.status, first.json()) == (200, {"status": "done", "params": {"code": "demo-0123", "state": ACME_STATE}})
    assert first.headers["cache-control"] == "no-store"
    assert _poll(weather, signer).json() == {"status": "pending"}


def test_nothing_posted_is_pending(weather, signer):
    assert _poll(weather, signer).json() == {"status": "pending"}


def test_a_state_made_for_another_organization_is_refused_and_not_kept(weather, signer):
    response = _post_result(weather, signer, {"state": "5.k3Jq9_x-Lm2Np4Qr6St8Uv", "params": {"code": "x"}})

    assert (response.status, response.json()) == (403, {"code": "state_mismatch"})
    for org in (ACME, CONTOSO):
        assert _poll(weather, signer, "5.k3Jq9_x-Lm2Np4Qr6St8Uv", org=org).json() == {"status": "pending"}


def test_another_person_in_the_organization_never_gets_the_result(weather, signer):
    _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "ada"}})

    assert _poll(weather, signer, person=EVE).json() == {"status": "pending"}
    assert _poll(weather, signer).json() == {"status": "done", "params": {"code": "ada"}}


def test_the_same_person_in_another_organization_never_gets_the_result(weather, signer):
    _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "ada"}})

    assert _poll(weather, signer, org=CONTOSO).json() == {"status": "pending"}
    assert _poll(weather, signer).json() == {"status": "done", "params": {"code": "ada"}}


def test_another_person_posting_the_same_state_does_not_replace_the_result(weather, signer):
    _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "ada"}})
    _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "eve"}}, person=EVE)

    assert _poll(weather, signer).json() == {"status": "done", "params": {"code": "ada"}}
    assert _poll(weather, signer, person=EVE).json() == {"status": "done", "params": {"code": "eve"}}


def test_a_result_posted_as_text_plain_is_accepted(weather, signer):
    # What `fetch(url, {method: "POST", body: JSON.stringify(...)})` sends without a header.
    response = _post_result(
        weather, signer, {"state": ACME_STATE, "params": {"code": "ada"}}, content_type="text/plain;charset=UTF-8"
    )

    assert response.status == 204
    assert _poll(weather, signer).json() == {"status": "done", "params": {"code": "ada"}}


def test_twenty_parameters_of_2048_characters_are_accepted(weather, signer):
    params = {f"name{index}": "v" * 2048 for index in range(20)}

    assert _post_result(weather, signer, {"state": ACME_STATE, "params": params}).status == 204
    assert _poll(weather, signer).json() == {"status": "done", "params": params}


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        {"state": ACME_STATE},
        {"params": {}},
        {"state": ACME_STATE, "params": {}, "org": 3},
        {"state": ACME_STATE, "params": []},
        {"state": ACME_STATE, "params": {"code": 1}},
        {"state": ACME_STATE, "params": {"code": None}},
        {"state": ACME_STATE, "params": {"code": ["a"]}},
        {"state": ACME_STATE, "params": {f"name{index}": "v" for index in range(21)}},
        {"state": ACME_STATE, "params": {"code": "v" * 2049}},
        {"state": ACME_STATE, "params": {"n" * 257: "v"}},
        {"state": "3.short", "params": {}},
        {"state": 3, "params": {}},
        {"state": f"{ACME_STATE}\n", "params": {}},
    ],
    ids=[
        "empty",
        "not json",
        "array",
        "no params",
        "no state",
        "extra key",
        "params a list",
        "number value",
        "null value",
        "list value",
        "21 parameters",
        "value too long",
        "name too long",
        "malformed state",
        "state a number",
        "state with a newline",
    ],
)
def test_a_malformed_result_is_refused(weather, signer, body):
    response = _post_result(weather, signer, body)

    assert (response.status, response.json()) == INVALID_REQUEST


def test_a_result_is_kept_for_its_person_in_its_organization(weather, signer, stores):
    _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "ada"}})

    assert stores.popup_relay.results == {(3, 42, ACME_STATE): {"code": "ada"}}


@pytest.mark.parametrize("state", ["not-a-state", "3.short", "0.k3Jq9_x-Lm2Np4Qr6St8Uv", "3." + "a" * 65])
def test_polling_a_state_that_cannot_exist_is_pending_without_a_lookup(weather, signer, stores, state):
    response = _poll(weather, signer, state)

    assert (response.status, response.json()) == (200, {"status": "pending"})
    assert stores.popup_relay.lookups == 0


def test_the_popup_state_pattern_is_the_login_protocols(sample_modules):
    protocol = json.loads(LOGIN_PROTOCOL.read_text())

    assert sample_modules.popup_relay.POPUP_STATE_PATTERN == protocol["patterns"]["popup_state"]


# --- The install hook ---


def _install(weather, signer, *, job_id=41, attempt=1):
    call = HookSigner(signer).call("install", org=ACME, job_id=job_id, attempt=attempt)
    return request(weather, "POST", call.path, call.headers, call.body)


def test_the_install_hook_creates_the_flow_and_the_readme(weather, signer, epicstaff_api, sample_modules):
    response = _install(weather, signer)

    assert (response.status, response.json()) == (200, {"status": "done"})
    (graph_id, graph), = epicstaff_api.graphs.items()
    assert graph["name"] == "Weather forecast"
    contents = graph["contents"]
    (python_node,) = contents["python_node_list"]
    assert (python_node["node_name"], python_node["input_map"], python_node["output_variable_path"]) == (
        "Fetch forecast",
        {"city": "variables.city"},
        "variables.forecast",
    )
    assert contents["start_node_list"][0]["variables"] == {"variables": {"city": "Berlin", "forecast": None}}
    (schedule,) = contents["schedule_trigger_node_list"]
    assert schedule["is_active"] is False
    assert schedule["schedule"]["run_mode"] == "repeat"
    assert schedule["schedule"]["interval"] == {"every": 1, "unit": "days", "weekdays": []}
    assert schedule["schedule"]["start_date_time"].endswith("T06:00:00")
    assert schedule["schedule"]["timezone"] == "UTC"
    assert epicstaff_api.files["weather/README.md"].startswith(b"# Weather")


def test_the_install_hook_acts_as_the_plugin_alone(weather, signer, epicstaff_api):
    _install(weather, signer)

    assert epicstaff_api.requests
    for sent in epicstaff_api.requests:
        assert sent.headers["authorization"] == f"PluginKey {ACME_KEY}"
        assert sent.headers["x-organization-id"] == "3"
        assert "x-epicstaff-on-behalf-of" not in sent.headers


def test_the_flow_edges_connect_start_and_schedule_to_the_fetch_and_the_fetch_to_the_end(weather, signer, epicstaff_api):
    _install(weather, signer)
    contents = next(iter(epicstaff_api.graphs.values()))["contents"]
    temp_ids = {
        name: contents[key][0]["temp_id"]
        for name, key in [("start", "start_node_list"), ("fetch", "python_node_list"), ("end", "end_node_list"), ("schedule", "schedule_trigger_node_list")]
    }

    edges = {(edge["start_temp_id"], edge["end_temp_id"]) for edge in contents["edge_list"]}

    assert edges == {
        (temp_ids["start"], temp_ids["fetch"]),
        (temp_ids["schedule"], temp_ids["fetch"]),
        (temp_ids["fetch"], temp_ids["end"]),
    }


def test_running_the_install_hook_twice_creates_one_flow_and_one_readme(weather, signer, epicstaff_api):
    assert _install(weather, signer).status == 200
    writes_after_first = len(epicstaff_api.writes())

    assert _install(weather, signer, attempt=2).status == 200

    assert len(epicstaff_api.graphs) == 1
    assert list(epicstaff_api.files) == ["weather/README.md"]
    assert len(epicstaff_api.writes()) == writes_after_first


def test_a_retried_install_hook_finishes_a_flow_an_earlier_attempt_left_empty(weather, signer, epicstaff_api):
    epicstaff_api.refusals[("POST", "graphs/101/save/")] = (503, "unavailable", "Try again.")
    failed = _install(weather, signer)
    assert failed.status == 500
    assert epicstaff_api.graphs[101]["contents"] is None
    del epicstaff_api.refusals[("POST", "graphs/101/save/")]

    assert _install(weather, signer, attempt=2).status == 200

    assert list(epicstaff_api.graphs) == [101]
    assert epicstaff_api.graphs[101]["contents"]["python_node_list"][0]["node_name"] == "Fetch forecast"


def test_an_epicstaff_refusal_fails_the_install_hook_with_its_message(weather, signer, epicstaff_api):
    epicstaff_api.refusals[("POST", "graphs/")] = (403, "permission_denied", "You do not have permission to perform this action.")

    response = _install(weather, signer)

    assert (response.status, response.json()) == (
        500,
        {
            "status": "failed",
            "error": {
                "message": "EpicStaff refused POST graphs/: 403 permission_denied: You do not have permission to perform this action."
            },
        },
    )
    assert epicstaff_api.files == {}


def test_the_readme_lookup_fails_the_hook_on_anything_but_not_found(weather, signer, epicstaff_api):
    epicstaff_api.refusals[("GET", "storage/info/")] = (403, "permission_denied", "No.")

    assert _install(weather, signer).status == 500
    assert epicstaff_api.files == {}


def test_the_install_hook_tags_the_flow_it_creates(weather, signer, epicstaff_api, sample_modules):
    forecast_flow = importlib.import_module("weather_plugin.forecast_flow")

    _install(weather, signer)

    (graph,) = epicstaff_api.graphs.values()
    assert forecast_flow.FLOW_TAG in graph["description"]


def test_a_persons_own_flow_of_that_name_is_left_alone(weather, signer, epicstaff_api, sample_modules):
    theirs = epicstaff_api.add_graph("Weather forecast", "Ada's own forecast experiments.")

    assert _install(weather, signer).status == 200

    assert epicstaff_api.graphs[theirs] == {"name": "Weather forecast", "description": "Ada's own forecast experiments.", "save_version": 1, "contents": None}
    (ours,) = [graph_id for graph_id in epicstaff_api.graphs if graph_id != theirs]
    assert epicstaff_api.graphs[ours]["name"] == "Weather forecast (Weather plugin)"
    assert epicstaff_api.graphs[ours]["contents"]["python_node_list"][0]["node_name"] == "Fetch forecast"
    status = request(weather, "GET", "/api/forecast/status", _as(signer, "GET", "/api/forecast/status"))
    assert status.json() == {"flow": {"id": ours, "name": "Weather forecast (Weather plugin)"}}


def test_a_forecast_never_runs_a_persons_flow_of_that_name(weather, signer, epicstaff_api):
    epicstaff_api.add_graph("Weather forecast", "Mentions the Weather forecast, but is not Weather's.")

    response = _start_forecast(weather, signer, {"city": "Paris"})

    assert (response.status, response.json()) == (409, {"code": "not_installed"})
    assert epicstaff_api.sessions == {}


def test_the_tagged_flow_is_found_whatever_its_name(weather, signer, epicstaff_api, sample_modules):
    forecast_flow = importlib.import_module("weather_plugin.forecast_flow")
    _install(weather, signer)
    (graph_id,) = epicstaff_api.graphs
    epicstaff_api.graphs[graph_id]["name"] = "Forecasts (renamed by an admin)"

    assert _install(weather, signer, attempt=2).status == 200

    assert list(epicstaff_api.graphs) == [graph_id]
    assert forecast_flow.FLOW_TAG in epicstaff_api.graphs[graph_id]["description"]


def test_the_flows_python_code_returns_the_forecast_the_backend_reads(monkeypatch, sample_modules):
    forecast_flow = importlib.import_module("weather_plugin.forecast_flow")
    forecast_runs = importlib.import_module("weather_plugin.forecast_runs")
    answers = {
        "geocoding-api.open-meteo.com": {"results": [{"name": "Paris", "latitude": 48.85, "longitude": 2.35}]},
        "api.open-meteo.com": {"daily": {"time": ["2026-10-21", "2026-10-22"], "temperature_2m_max": [17.5, 15.0], "temperature_2m_min": [9.0, 8.5]}},
    }
    asked = []

    def urlopen(url, timeout):
        asked.append(url)
        host = url.split("/")[2]
        return io.BytesIO(json.dumps(answers[host]).encode())

    namespace = {}
    exec(compile(forecast_flow.FETCH_FORECAST_CODE, "fetch_forecast", "exec"), namespace)
    monkeypatch.setattr(namespace["urllib"].request, "urlopen", urlopen)

    forecast = namespace["main"](city=" Paris ")

    assert forecast == {
        "city": "Paris",
        "days": [
            {"date": "2026-10-21", "temperature_max": 17.5, "temperature_min": 9.0},
            {"date": "2026-10-22", "temperature_max": 15.0, "temperature_min": 8.5},
        ],
    }
    assert forecast_runs.Forecast.model_validate(forecast).model_dump() == forecast
    assert "name=Paris" in asked[0]


def test_the_schedule_starts_on_the_day_the_hook_runs(sample_modules):
    forecast_flow = importlib.import_module("weather_plugin.forecast_flow")

    contents = forecast_flow.flow_contents(7, 1, datetime(2026, 10, 21, 18, 30, tzinfo=UTC))

    assert contents["schedule_trigger_node_list"][0]["schedule"]["start_date_time"] == "2026-10-21T06:00:00"
    assert contents["save_version"] == 1
    assert all(node["graph"] == 7 for key in ("start_node_list", "python_node_list", "end_node_list") for node in contents[key])


# --- The forecast, for a person ---


def _as(signer, method, path, person=ADA, org=ACME, permissions=("read",)):
    return signer.headers(method, path, mode="user", user=person, org=org, permissions=list(permissions))


def _start_forecast(weather, signer, body, person=ADA, org=ACME):
    headers = {**_as(signer, "POST", "/api/forecast", person, org), "content-type": "application/json"}
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return request(weather, "POST", "/api/forecast", headers, raw)


def _forecast(weather, signer, session_id, person=ADA, org=ACME):
    path = f"/api/forecast/{session_id}"
    return request(weather, "GET", path, _as(signer, "GET", path, person, org))


def test_the_status_has_no_flow_before_the_install_hook_ran(weather, signer):
    response = request(weather, "GET", "/api/forecast/status", _as(signer, "GET", "/api/forecast/status"))

    assert (response.status, response.json()) == (200, {"flow": None})


def test_the_status_names_the_flow_once_installed(weather, signer, epicstaff_api):
    _install(weather, signer)

    response = request(weather, "GET", "/api/forecast/status", _as(signer, "GET", "/api/forecast/status"))

    assert response.json() == {"flow": {"id": 101, "name": "Weather forecast"}}
    assert epicstaff_api.requests[-1].headers["x-epicstaff-on-behalf-of"] == "42"


def test_a_forecast_runs_the_flow_on_behalf_of_the_person(weather, signer, epicstaff_api, stores):
    _install(weather, signer)

    response = _start_forecast(weather, signer, {"city": " Paris "})

    assert response.status == 202
    session_id = response.json()["session_id"]
    run = next(sent for sent in epicstaff_api.requests if sent.path == "run-session/")
    assert run.body == {"graph_id": 101, "variables": {"city": "Paris"}}
    assert run.headers["x-epicstaff-on-behalf-of"] == "42"
    assert epicstaff_api.sessions[session_id]["graph"] == 101
    assert stores.forecast_runs.runs == {(3, session_id): (42, "Paris")}


def test_a_forecast_before_the_install_hook_ran_is_refused(weather, signer, epicstaff_api):
    response = _start_forecast(weather, signer, {"city": "Paris"})

    assert (response.status, response.json()) == (409, {"code": "not_installed"})
    assert epicstaff_api.sessions == {}


def test_an_organization_without_a_service_account_is_not_installed(weather, signer):
    response = _start_forecast(weather, signer, {"city": "Paris"}, org=CONTOSO)

    assert (response.status, response.json()) == (409, {"code": "not_installed"})


@pytest.mark.parametrize(
    "body",
    [b"", b"not json", {}, {"city": ""}, {"city": "   "}, {"city": "x" * 101}, {"city": 7}, {"city": "Paris", "days": 3}],
    ids=["empty", "not json", "no city", "empty city", "blank city", "city too long", "city a number", "extra key"],
)
def test_a_malformed_forecast_request_is_refused(weather, signer, epicstaff_api, body):
    _install(weather, signer)

    response = _start_forecast(weather, signer, body)

    assert (response.status, response.json()) == INVALID_REQUEST
    assert epicstaff_api.sessions == {}


@pytest.mark.parametrize(
    ("status", "status_data", "expected"),
    [
        ("pending", {}, "pending"),
        ("run", {}, "running"),
        ("wait_for_user", {}, "running"),
        ("error", {"variables": {}}, "failed"),
        ("stop", {}, "failed"),
        ("expired", {}, "failed"),
    ],
)
def test_a_forecast_reports_the_runs_state(weather, signer, epicstaff_api, status, status_data, expected):
    _install(weather, signer)
    session_id = _start_forecast(weather, signer, {"city": "Paris"}).json()["session_id"]
    epicstaff_api.sessions[session_id].update(status=status, status_data=status_data)

    response = _forecast(weather, signer, session_id)

    assert (response.status, response.json()) == (200, {"status": expected, "forecast": None})
    assert response.headers["cache-control"] == "no-store"


def test_a_finished_forecast_carries_the_forecast(weather, signer, epicstaff_api):
    _install(weather, signer)
    session_id = _start_forecast(weather, signer, {"city": "Paris"}).json()["session_id"]
    forecast = {"city": "Paris", "days": [{"date": "2026-10-21", "temperature_max": 17.5, "temperature_min": 9.0}]}
    epicstaff_api.sessions[session_id].update(status="end", status_data={"variables": {"city": "Paris", "forecast": forecast}})

    assert _forecast(weather, signer, session_id).json() == {"status": "finished", "forecast": forecast}


def test_a_finished_run_without_a_forecast_has_none(weather, signer, epicstaff_api):
    _install(weather, signer)
    session_id = _start_forecast(weather, signer, {"city": "Paris"}).json()["session_id"]
    epicstaff_api.sessions[session_id].update(status="end", status_data={"variables": {"forecast": "not a forecast"}})

    assert _forecast(weather, signer, session_id).json() == {"status": "finished", "forecast": None}


def test_a_forecast_is_only_for_the_person_who_started_it(weather, signer, epicstaff_api):
    _install(weather, signer)
    session_id = _start_forecast(weather, signer, {"city": "Paris"}).json()["session_id"]

    assert _forecast(weather, signer, session_id, person=EVE).json() == {"code": "not_found"}
    assert _forecast(weather, signer, session_id, org=CONTOSO).status == 404
    assert _forecast(weather, signer, session_id).status == 200


@pytest.mark.parametrize("session_id", ["999", "abc", "-1", "0", "\u0663", str(2**63)])
def test_a_forecast_weather_did_not_start_is_not_found(weather, signer, epicstaff_api, session_id):
    epicstaff_api.sessions[999] = {"id": 999, "status": "end", "status_data": {}}

    response = _forecast(weather, signer, session_id)

    assert (response.status, response.json()) == (404, {"code": "not_found"})


# --- Organization settings, for people with the delete permission ---

SETTINGS_ROUTES = [("GET", "/api/org-settings"), ("GET", "/api/llm-models"), ("PUT", "/api/org-settings/llm")]
LLM_SETUP = {"llm_model_id": 7, "api_key": "sk-live-0123456789"}
ADMIN_PERMISSIONS = ("read", "delete")


def _olga_may_set_up(epicstaff_api, **epicstaff_permissions):
    epicstaff_api.people[OLGA["id"]] = {
        "user": OLGA,
        "organization": ACME,
        "plugin_permissions": list(ADMIN_PERMISSIONS),
        "epicstaff_permissions": epicstaff_permissions or {"secrets": ["read", "create", "delete", "use"], "llm_configs": ["read", "create", "update", "delete"]},
    }


def _settings_call(weather, signer, method, path, body=None, permissions=ADMIN_PERMISSIONS, person=OLGA):
    headers = {**_as(signer, method, path, person, permissions=permissions), "content-type": "application/json"}
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    return request(weather, method, path, headers, raw)


@pytest.mark.parametrize(("method", "path"), SETTINGS_ROUTES)
def test_organization_settings_need_the_delete_permission(weather, signer, epicstaff_api, method, path):
    response = _settings_call(weather, signer, method, path, LLM_SETUP if method == "PUT" else None, permissions=("read",), person=ADA)

    assert (response.status, response.json()) == (403, {"code": "forbidden"})
    assert epicstaff_api.requests == []


def test_organization_settings_start_without_an_llm_config(weather, signer):
    response = _settings_call(weather, signer, "GET", "/api/org-settings")

    assert (response.status, response.json()) == (200, {"llm_config": None})


def test_the_model_list_is_read_page_by_page(weather, signer, epicstaff_api):
    response = _settings_call(weather, signer, "GET", "/api/llm-models")

    assert response.status == 200
    assert response.json()[:2] == [{"id": 1, "name": "model-1"}, {"id": 2, "name": "model-2"}]
    assert len(response.json()) == 250
    assert [sent.params["offset"] for sent in epicstaff_api.requests] == ["0", "200"]
    assert all(sent.headers["x-epicstaff-on-behalf-of"] == "44" for sent in epicstaff_api.requests)


def test_setting_up_the_llm_creates_the_secret_and_the_config_on_behalf_of_the_admin(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    assert response.status == 200
    (secret_id, secret), = epicstaff_api.secrets.items()
    assert secret == {"name": "Weather \u00b7 LLM key", "value": "sk-live-0123456789"}
    (config_id, config), = epicstaff_api.llm_configs.items()
    assert config == {"custom_name": "Weather summaries", "model": 7, "api_key_secret_id": secret_id}
    assert response.json() == {"llm_config": {"id": config_id, "name": "Weather summaries"}}
    assert b"sk-live" not in response.body
    for write in epicstaff_api.writes():
        assert write.headers["x-epicstaff-on-behalf-of"] == "44"
    assert _settings_call(weather, signer, "GET", "/api/org-settings").json() == {"llm_config": {"id": config_id, "name": "Weather summaries"}}


def test_the_llm_is_set_up_once(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)
    _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", {**LLM_SETUP, "api_key": "another"})

    assert (response.status, response.json()) == (409, {"code": "already_configured"})
    assert len(epicstaff_api.secrets) == 1


def test_an_admin_without_the_epicstaff_rights_to_create_secrets_is_refused(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api, secrets=["read"], llm_configs=["read", "create"])

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    assert (response.status, response.json()) == (403, {"code": "forbidden"})
    assert epicstaff_api.writes() == []


def test_an_admin_epicstaff_does_not_list_is_refused(weather, signer, epicstaff_api):
    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    assert (response.status, response.json()) == (403, {"code": "forbidden"})
    assert epicstaff_api.writes() == []


def test_an_unknown_model_is_refused_before_anything_is_created(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", {**LLM_SETUP, "llm_model_id": 9999})

    assert (response.status, response.json()) == INVALID_REQUEST
    assert epicstaff_api.secrets == {}


def test_an_epicstaff_refusal_is_reported_with_its_message(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)
    epicstaff_api.refusals[("POST", "secrets/")] = (403, "permission_denied", "You do not have permission to perform this action.")

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    assert (response.status, response.json()) == (
        502,
        {"code": "epicstaff_error", "message": "You do not have permission to perform this action."},
    )


@pytest.mark.parametrize(
    "body",
    [
        b"",
        {"llm_model_id": 7},
        {"api_key": "sk"},
        {"llm_model_id": "7", "api_key": "sk"},
        {"llm_model_id": 0, "api_key": "sk"},
        {"llm_model_id": 7, "api_key": ""},
        {"llm_model_id": 7, "api_key": "k" * 4097},
        {"llm_model_id": 7, "api_key": "sk-secret-value", "extra": 1},
    ],
    ids=["empty", "no key", "no model", "model as text", "model 0", "empty key", "key too long", "extra key"],
)
def test_a_malformed_llm_setup_is_refused_without_echoing_the_key(weather, signer, epicstaff_api, body):
    _olga_may_set_up(epicstaff_api)

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", body)

    assert (response.status, response.json()) == INVALID_REQUEST
    assert b"sk-secret-value" not in response.body
    assert epicstaff_api.writes() == []


def test_a_secret_left_behind_by_a_failed_setup_is_used_when_the_admin_enters_the_same_key(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)
    epicstaff_api.refusals[("POST", "llm-configs/")] = (503, "unavailable", "Try again.")
    failed = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)
    assert failed.status == 502
    (secret_id,) = epicstaff_api.secrets
    del epicstaff_api.refusals[("POST", "llm-configs/")]

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    assert response.status == 200
    assert list(epicstaff_api.secrets) == [secret_id]
    (config,) = epicstaff_api.llm_configs.values()
    assert config["api_key_secret_id"] == secret_id


def test_a_secret_left_behind_with_another_key_is_never_used(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)
    epicstaff_api.add_secret("Weather \u00b7 LLM key", "sk-old-key-0000")

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    assert (response.status, response.json()) == (
        409,
        {
            "code": "secret_exists",
            "message": 'A Secret named "Weather \u00b7 LLM key" already exists with another key. Delete it in '
            "Settings \u2192 Secrets, then set up the LLM again.",
        },
    )
    assert len(epicstaff_api.secrets) == 1
    assert epicstaff_api.llm_configs == {}


def test_a_secret_whose_key_epicstaff_does_not_show_is_never_used(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)
    epicstaff_api.add_secret("Weather \u00b7 LLM key", "short")

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", {**LLM_SETUP, "api_key": "short"})

    assert (response.status, response.json()["code"]) == (409, "secret_exists")
    assert epicstaff_api.llm_configs == {}


def test_other_secrets_are_not_taken_for_weathers(weather, signer, epicstaff_api):
    _olga_may_set_up(epicstaff_api)
    epicstaff_api.add_secret("Another plugin's key", "sk-live-0123456789")

    response = _settings_call(weather, signer, "PUT", "/api/org-settings/llm", LLM_SETUP)

    assert response.status == 200
    assert sorted(secret["name"] for secret in epicstaff_api.secrets.values()) == ["Another plugin's key", "Weather \u00b7 LLM key"]


# --- Saved places, kept per organization ---

EDITOR = ("read", "update")


def _places_call(weather, signer, method, path, body=None, *, person=ADA, org=ACME, permissions=EDITOR, query=""):
    headers = {**_as(signer, method, path, person, org, permissions=permissions), "content-type": "application/json"}
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    return request(weather, method, path, headers, raw, query=query)


@pytest.mark.parametrize(
    ("method", "path", "query"),
    [("GET", "/api/places", ""), ("GET", "/api/places/search", "q=Lisbon"), ("POST", "/api/places", ""), ("DELETE", "/api/places/1", "")],
)
def test_places_are_for_logged_in_people_only(weather, signer, method, path, query):
    response = request(weather, method, path, signer.headers(method, path), query=query)

    assert (response.status, response.json()) == (401, {"code": "login_required"})


def test_the_list_shows_only_the_organizations_own_places(weather, signer, stores):
    lisbon = stores.places.seed(3, 42, "Lisbon", "Portugal", 38.7, -9.1, admin1="Lisbon")
    stores.places.seed(5, 77, "Kyiv", "Ukraine", 50.45, 30.52)

    response = _places_call(weather, signer, "GET", "/api/places", permissions=("read",))

    assert response.status == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "places": [
            {"id": lisbon.id, "name": "Lisbon", "admin1": "Lisbon", "country": "Portugal", "latitude": 38.7, "longitude": -9.1, "created_at": "2026-10-21T12:00:00Z"}
        ]
    }


def test_adding_a_search_result_saves_it_for_the_persons_organization(weather, signer, stores):
    response = _places_call(weather, signer, "POST", "/api/places", LISBON)

    assert response.status == 201
    body = response.json()
    assert {key: body[key] for key in ("name", "admin1", "country", "latitude", "longitude")} == {
        "name": "Lisbon",
        "admin1": "Lisbon",
        "country": "Portugal",
        "latitude": 38.71667,
        "longitude": -9.13333,
    }
    ((org_id, created_by, saved),) = stores.places.rows.values()
    assert (org_id, created_by, saved.id) == (3, 42, body["id"])


@pytest.mark.parametrize(("method", "path"), [("POST", "/api/places"), ("DELETE", "/api/places/1")])
def test_adding_and_removing_places_need_the_update_permission(weather, signer, stores, method, path):
    stores.places.seed(3, 42, "Lisbon", "Portugal")

    response = _places_call(weather, signer, method, path, LISBON if method == "POST" else None, person=EVE, permissions=("read",))

    assert (response.status, response.json()) == (403, {"code": "forbidden"})
    assert len(stores.places.rows) == 1


@pytest.mark.parametrize("admin1", ["Lisbon", None], ids=["with a region", "without a region"])
def test_a_place_the_organization_already_saved_is_refused(weather, signer, stores, admin1):
    stores.places.seed(3, 44, "Lisbon", "Portugal", admin1=admin1)

    response = _places_call(weather, signer, "POST", "/api/places", {**LISBON, "admin1": admin1})

    assert (response.status, response.json()) == (409, {"code": "already_saved"})
    assert len(stores.places.rows) == 1


def test_places_of_one_name_in_one_country_are_told_apart_by_their_region(weather, signer, stores):
    springfield = {"name": "Springfield", "country": "United States", "latitude": 39.8, "longitude": -89.64}
    stores.places.seed(3, 44, "Springfield", "United States", admin1="Illinois")

    missouri = _places_call(weather, signer, "POST", "/api/places", {**springfield, "admin1": "Missouri"})
    no_region = _places_call(weather, signer, "POST", "/api/places", {**springfield, "admin1": None})
    listed = _places_call(weather, signer, "GET", "/api/places")

    assert (missouri.status, no_region.status) == (201, 201)
    assert [place["admin1"] for place in listed.json()["places"]] == [None, "Illinois", "Missouri"]


def test_another_organization_may_save_the_same_place(weather, signer, stores):
    stores.places.seed(5, 77, "Lisbon", "Portugal")

    assert _places_call(weather, signer, "POST", "/api/places", LISBON).status == 201


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        {key: value for key, value in LISBON.items() if key != "country"},
        {**LISBON, "name": ""},
        {**LISBON, "country": "c" * 101},
        {**LISBON, "latitude": 91},
        {**LISBON, "longitude": "-9.1"},
        {**LISBON, "latitude": True},
        {**LISBON, "org_id": 5},
    ],
    ids=["empty", "not json", "no country", "empty name", "country too long", "latitude off the globe", "longitude as text", "latitude a boolean", "extra key"],
)
def test_a_malformed_place_is_refused(weather, signer, stores, body):
    response = _places_call(weather, signer, "POST", "/api/places", body)

    assert (response.status, response.json()) == INVALID_REQUEST
    assert stores.places.rows == {}


def test_removing_a_place(weather, signer, stores):
    lisbon = stores.places.seed(3, 44, "Lisbon", "Portugal")

    response = _places_call(weather, signer, "DELETE", f"/api/places/{lisbon.id}")

    assert (response.status, response.body) == (204, b"")
    assert stores.places.rows == {}


@pytest.mark.parametrize("place_id", ["other-org", "999", "abc", "0", "-1", str(2**63)])
def test_removing_another_organizations_or_an_unknown_place_is_not_found(weather, signer, stores, place_id):
    kyiv = stores.places.seed(5, 77, "Kyiv", "Ukraine")
    path = f"/api/places/{kyiv.id if place_id == 'other-org' else place_id}"

    response = _places_call(weather, signer, "DELETE", path)

    assert (response.status, response.json()) == (404, {"code": "not_found"})
    assert list(stores.places.rows) == [kyiv.id]


# --- Place search, through the egress proxy ---


def test_a_search_asks_the_geocoding_api_for_five_places_by_name(weather, signer, geocoding):
    response = _places_call(weather, signer, "GET", "/api/places/search", permissions=("read",), query="q=%20Lisbon%20")

    assert response.status == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "results": [
            LISBON,
            {"name": "Lisbon", "country": "United States", "admin1": "Maine", "latitude": 44.03, "longitude": -70.1},
        ]
    }
    (sent,) = geocoding.requests
    assert (sent.method, str(sent.url.copy_with(query=None)), dict(sent.url.params)) == (
        "GET",
        GEOCODING_URL,
        {"name": "Lisbon", "count": "5", "format": "json"},
    )


def test_a_search_that_finds_nothing_has_no_results(weather, signer, geocoding):
    geocoding.answer = httpx.Response(200, json={"generationtime_ms": 0.4})

    response = _places_call(weather, signer, "GET", "/api/places/search", query="q=Nowhereville")

    assert (response.status, response.json()) == (200, {"results": []})


@pytest.mark.parametrize(
    "query",
    ["", "q=", "q=%20%20", "q=" + "x" * 101, "q=a&q=b", "q=a&count=9", "name=Lisbon"],
    ids=["nothing", "empty", "blank", "too long", "repeated", "extra parameter", "no q"],
)
def test_a_malformed_search_is_refused_without_a_lookup(weather, signer, geocoding, query):
    response = _places_call(weather, signer, "GET", "/api/places/search", query=query)

    assert (response.status, response.json()) == INVALID_REQUEST
    assert geocoding.requests == []


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500, text="upstream down"),
        httpx.Response(429, json={"error": True, "reason": "Too many requests"}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"results": [{"name": "Lisbon"}]}),
        httpx.Response(200, json={"results": [{**LISBON, "latitude": 300}]}),
        httpx.ProxyError("403 Forbidden"),
        httpx.ConnectError("unreachable"),
        httpx.ReadTimeout("slow"),
    ],
    ids=["server error", "rate limited", "not json", "no coordinates", "latitude off the globe", "proxy refusal", "unreachable", "timeout"],
)
def test_a_failed_lookup_is_lookup_failed(weather, signer, geocoding, answer):
    geocoding.answer = answer

    response = _places_call(weather, signer, "GET", "/api/places/search", query="q=Lisbon")

    assert (response.status, response.json()) == (502, {"code": "lookup_failed"})


def test_the_search_goes_through_the_egress_proxy_and_epicstaff_calls_do_not(monkeypatch, tmp_path, signer, sample_modules, stores):
    with serving(RefusingProxy()) as proxy, serving(EmptyApi()) as epicstaff_api:
        proxy_url = f"http://weather:proxy-password@127.0.0.1:{proxy.port}"
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            monkeypatch.setenv(name, proxy_url)
        for name in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.delenv(name, raising=False)
        runtime_file = tmp_path / "runtime.json"
        write_runtime_file(
            runtime_file,
            signer=signer,
            epicstaff_api_url=f"http://127.0.0.1:{epicstaff_api.port}/api/",
            service_accounts={"3": {"key": ACME_KEY, "org_name": "Acme", "grant_state": "active"}},
        )
        runtime = RuntimeConfig.load(runtime_file)
        # Both clients as the app makes them, on the network.
        epicstaff = EpicStaffClient(runtime)
        place_search = sample_modules.place_search.PlaceSearch()
        weather = _serve_with(monkeypatch, sample_modules.app, runtime, epicstaff, stores, place_search)

        search = _places_call(weather, signer, "GET", "/api/places/search", query="q=Lisbon")
        status = request(weather, "GET", "/api/forecast/status", _as(signer, "GET", "/api/forecast/status"))
        asyncio.run(place_search.aclose())
        asyncio.run(epicstaff.aclose())

    assert (search.status, search.json()) == (502, {"code": "lookup_failed"})
    ((connect, *headers),) = proxy.requests
    assert connect == "CONNECT geocoding-api.open-meteo.com:443 HTTP/1.1"
    credentials = base64.b64encode(b"weather:proxy-password").decode()
    assert f"Proxy-Authorization: Basic {credentials}" in headers
    assert (status.status, status.json()) == (200, {"flow": None})
    assert epicstaff_api.paths == ["/api/graph-light/"]
