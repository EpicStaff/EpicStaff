import importlib
import io
import json
import re
import tomllib
from datetime import UTC, datetime

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


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def sample_modules(monkeypatch):
    """The sample backend's modules, imported from its source directory."""
    monkeypatch.syspath_prepend(str(SAMPLE / "backend" / "src"))
    return importlib.import_module("weather_plugin.app"), importlib.import_module("weather_plugin.popup_relay")


@pytest.fixture
def relay_clock():
    return FakeClock()


@pytest.fixture
def epicstaff_api():
    """EpicStaff's API as the sample sees it, for organization 3 (Acme)."""
    return FakeEpicStaff(org_id=ACME["id"])


@pytest.fixture
def weather(monkeypatch, tmp_path, signer, sample_modules, relay_clock, epicstaff_api):
    """The sample's app, served as the node serves it, with `units` set to imperial.

    It holds a service account for Acme and calls `epicstaff_api`. Its popup relay and its
    forecast runs start empty in every test; the relay runs on `relay_clock`.
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
    app_module, relay_module = sample_modules
    runtime = RuntimeConfig.load(runtime_file)
    epicstaff = EpicStaffClient(runtime, transport=epicstaff_api.transport())
    monkeypatch.setattr(app_module.app.state, "popup_relay", relay_module.PopupRelayStore(clock=relay_clock))
    monkeypatch.setattr(app_module.app.state, "forecast_runs", importlib.import_module("weather_plugin.forecast_runs").ForecastRuns())
    monkeypatch.setattr(app_module.app.state, "epicstaff", epicstaff)
    return build_app(app_module.app, runtime, epicstaff=epicstaff)


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

    assert source.problems(source.describe(), require_sdk_pin=False) == []
    assert source.manifest.version == "0.4.0"
    assert source.manifest.hooks.install
    assert {declaration.resource_type: declaration.actions for declaration in source.manifest.access} == {
        "flows": ["read", "create", "update", "use"],
        "files": ["read", "create"],
        "secrets": ["read", "create", "use"],
        "llm_configs": ["read", "create"],
    }
    assert source.manifest.user_permission_defaults("org_admin") == ["read", "delete"]
    assert source.manifest.user_permission_defaults("member") == ["read"]
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


def test_a_result_is_kept_for_five_minutes(weather, signer, relay_clock):
    _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "ada"}})
    relay_clock.now += 299
    assert _poll(weather, signer).json()["status"] == "done"

    _post_result(weather, signer, {"state": ACME_STATE, "params": {"code": "ada"}})
    relay_clock.now += 300
    assert _poll(weather, signer).json() == {"status": "pending"}


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


@pytest.mark.parametrize("state", ["not-a-state", "3.short", "0.k3Jq9_x-Lm2Np4Qr6St8Uv"])
def test_polling_a_state_that_cannot_exist_is_pending(weather, signer, state):
    response = _poll(weather, signer, state)

    assert (response.status, response.json()) == (200, {"status": "pending"})


def test_the_store_drops_the_oldest_result_when_full(sample_modules, relay_clock):
    _, relay_module = sample_modules
    store = relay_module.PopupRelayStore(clock=relay_clock)
    limit = relay_module.MAX_STORED_RESULTS

    for index in range(limit + 1):
        store.put(42, 3, f"3.{index:022d}", {"code": str(index)})

    assert store.take(42, 3, f"3.{0:022d}") is None
    assert store.take(42, 3, f"3.{1:022d}") == {"code": "1"}
    assert store.take(42, 3, f"3.{limit:022d}") == {"code": str(limit)}


def test_the_popup_state_pattern_is_the_login_protocols(sample_modules):
    _, relay_module = sample_modules
    protocol = json.loads(LOGIN_PROTOCOL.read_text())

    assert relay_module.POPUP_STATE_PATTERN == protocol["patterns"]["popup_state"]


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


def test_a_forecast_runs_the_flow_on_behalf_of_the_person(weather, signer, epicstaff_api):
    _install(weather, signer)

    response = _start_forecast(weather, signer, {"city": " Paris "})

    assert response.status == 202
    session_id = response.json()["session_id"]
    run = next(sent for sent in epicstaff_api.requests if sent.path == "run-session/")
    assert run.body == {"graph_id": 101, "variables": {"city": "Paris"}}
    assert run.headers["x-epicstaff-on-behalf-of"] == "42"
    assert epicstaff_api.sessions[session_id]["graph"] == 101


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


@pytest.mark.parametrize("session_id", ["999", "abc", "-1"])
def test_a_forecast_this_process_did_not_start_is_not_found(weather, signer, epicstaff_api, session_id):
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
