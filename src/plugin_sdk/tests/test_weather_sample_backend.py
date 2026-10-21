import importlib
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


@pytest.fixture
def weather(monkeypatch, tmp_path, signer):
    """The sample's app, served as the node serves it, with `units` set to imperial."""
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(
        runtime_file,
        signer=signer,
        settings={"units": "imperial"},
        secret_settings={"forecast_api_token": "s3cret-token"},
    )
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    monkeypatch.syspath_prepend(str(SAMPLE / "backend" / "src"))
    module = importlib.import_module("weather_plugin.app")
    return build_app(module.app, RuntimeConfig.load(runtime_file))


def test_ping_answers_a_public_context(weather, signer):
    response = request(weather, "GET", "/api/ping", signer.headers("GET", "/api/ping"))

    assert (response.status, response.json()) == (200, {"status": "ok", "mode": "public"})


def test_ping_without_a_context_is_refused(weather):
    response = request(weather, "GET", "/api/ping")

    assert (response.status, response.json()) == (401, {"code": "context_invalid"})


def test_ping_with_a_context_for_another_path_is_refused(weather, signer):
    assert request(weather, "GET", "/api/ping", signer.headers("GET", "/api/whoami")).status == 401


def test_whoami_returns_the_context_it_was_sent(weather, signer):
    headers = signer.headers(
        "GET",
        "/api/whoami",
        mode="user",
        user={"id": 7, "email": "ada@example.com", "name": "Ada"},
        org={"id": 3, "name": "Acme"},
        permissions=["read"],
    )

    body = request(weather, "GET", "/api/whoami", headers).json()

    assert (body["mode"], body["user"]["email"], body["org"]["name"], body["permissions"]) == (
        "user",
        "ada@example.com",
        "Acme",
        ["read"],
    )


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
    assert source.manifest.version == "0.2.0"
    assert [public_path.path for public_path in source.manifest.public_paths] == ["/api/ping"]


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
