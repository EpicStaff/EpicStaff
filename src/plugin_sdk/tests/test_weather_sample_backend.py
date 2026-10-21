import importlib
import json
import re
import tomllib

import pytest
from packaging.requirements import Requirement

from asgi_client import request
from conftest import REPO_ROOT
from epicstaff_plugin.package_source import collect_source
from epicstaff_plugin.requirements_lock import parse_requirements_lock
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import write_runtime_file

SAMPLE = REPO_ROOT / "plugin-samples" / "weather"
SDK_PYPROJECT = REPO_ROOT / "src" / "plugin_sdk" / "pyproject.toml"
LOGIN_PROTOCOL = REPO_ROOT / "plugin-sdk" / "contracts" / "login-protocol.json"

ADA = {"id": 42, "email": "ada@acme.test", "name": "Ada"}
EVE = {"id": 43, "email": "eve@acme.test", "name": "Eve"}
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
def weather(monkeypatch, tmp_path, signer, sample_modules, relay_clock):
    """The sample's app, served as the node serves it, with `units` set to imperial.

    Its popup relay starts empty in every test and runs on `relay_clock`.
    """
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(
        runtime_file,
        signer=signer,
        settings={"units": "imperial"},
        secret_settings={"forecast_api_token": "s3cret-token"},
    )
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    app_module, relay_module = sample_modules
    monkeypatch.setattr(app_module.app.state, "popup_relay", relay_module.PopupRelayStore(clock=relay_clock))
    return build_app(app_module.app, RuntimeConfig.load(runtime_file))


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
    assert source.manifest.version == "0.3.0"
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
