"""A plugin process's environment: the platform's credentials for it, and nothing of the agent's."""

import asyncio
import sys
from pathlib import Path

import pytest
from epicstaff_plugin.contracts import runtime as runtime_contract
from epicstaff_plugin.contracts.runtime import RuntimeFile

from es_plugins.packages.venv_builder import build_venv
from es_plugins.packages.wheel_tag_check import supported_tags
from es_plugins.runtime.process_environment import PlatformCredentials, plugin_environment
from es_plugins.supervisor.process_supervisor import ProcessSpec
from tests.helpers import database_section, make_wheel, placement, runtime_file_document
from tests.test_venv_builder import backend, request_for

APP_PASSWORD = "A" * 20 + "-_" + "b" * 21
EGRESS_PASSWORD = "e" * 30 + "-_"
AGENT_SECRETS = {"PLUGINS_DB_ADMIN_PASSWORD": "d" * 64, "PLUGINS_NODE_KEY": "n" * 64}


def environment_of(layout, desired, credentials):
    runtime_file = RuntimeFile.model_validate(runtime_file_document())
    return plugin_environment(layout, desired, Path("/venv"), runtime_file, credentials)


def test_a_plugin_with_a_database_gets_its_url_its_connection_limit_and_the_proxy(layout):
    desired = placement(b"package", database=database_section(connection_limit=4))

    environment = environment_of(layout, desired, PlatformCredentials(EGRESS_PASSWORD, APP_PASSWORD))

    assert environment["DATABASE_URL"] == (
        f"postgresql://weather_app:{APP_PASSWORD}@plugins_db:5432/plugin_weather?application_name=weather"
    )
    assert environment["EPICSTAFF_PLUGIN_DB_CONNECTIONS"] == "4"
    proxy = f"http://weather:{EGRESS_PASSWORD}@plugins_egress:3128"
    assert {name: environment[name] for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")} == dict.fromkeys(
        ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"), proxy
    )
    # The runtime file's epicstaff_api_url is http://epicstaff-api:8081/api/.
    assert environment["NO_PROXY"] == environment["no_proxy"] == "epicstaff-api,localhost,127.0.0.1,::1"


def test_a_plugin_without_a_database_gets_the_proxy_and_no_database_variables(layout):
    environment = environment_of(layout, placement(b"package"), PlatformCredentials(EGRESS_PASSWORD))

    assert "DATABASE_URL" not in environment
    assert "EPICSTAFF_PLUGIN_DB_CONNECTIONS" not in environment
    assert environment["HTTPS_PROXY"] == f"http://weather:{EGRESS_PASSWORD}@plugins_egress:3128"


def test_the_variable_names_are_the_sdks(layout):
    desired = placement(b"package", database=database_section())

    environment = environment_of(layout, desired, PlatformCredentials(EGRESS_PASSWORD, APP_PASSWORD))

    sdk_names = {
        runtime_contract.DATABASE_URL_ENVIRONMENT_VARIABLE,
        runtime_contract.DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE,
        *runtime_contract.PROXY_ENVIRONMENT_VARIABLES,
        *runtime_contract.NO_PROXY_ENVIRONMENT_VARIABLES,
    }
    assert sdk_names <= set(environment)
    assert environment["NO_PROXY"].endswith(",".join(runtime_contract.LOOPBACK_NO_PROXY_HOSTS))


def test_a_placement_with_a_database_is_not_started_without_its_password(layout):
    desired = placement(b"package", database=database_section())

    with pytest.raises(ValueError):
        environment_of(layout, desired, PlatformCredentials(EGRESS_PASSWORD))


def test_nothing_of_the_agents_environment_reaches_a_plugin(layout, monkeypatch):
    for name, value in AGENT_SECRETS.items():
        monkeypatch.setenv(name, value)
    desired = placement(b"package", database=database_section())

    environment = environment_of(layout, desired, PlatformCredentials(EGRESS_PASSWORD, APP_PASSWORD))

    for name, value in AGENT_SECRETS.items():
        assert name not in environment
        assert not [text for text in environment.values() if value in text]


def test_the_credentials_are_never_shown_in_a_representation(layout):
    desired = placement(b"package", database=database_section())
    credentials = PlatformCredentials(EGRESS_PASSWORD, APP_PASSWORD)
    spec = ProcessSpec(
        plugin="weather",
        uid=20001,
        version="0.2.0",
        argv=["/venv/bin/python"],
        environment=environment_of(layout, desired, credentials),
        nice=0,
        port=20001,
        memory_mb=256,
    )

    for shown in (repr(credentials), repr(spec)):
        assert APP_PASSWORD not in shown and EGRESS_PASSWORD not in shown


async def test_no_subprocess_of_the_agent_gets_the_node_key_or_the_database_admin_password(tmp_path, monkeypatch):
    for name, value in AGENT_SECRETS.items():
        monkeypatch.setenv(name, value)
    environments = []
    start_process = asyncio.create_subprocess_exec

    async def recording(*arguments, **options):
        environments.append(options.get("env"))
        return await start_process(*arguments, **options)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording)
    wheels = [make_wheel(tmp_path / "built", "uvicorn", "0.52.3")]

    await supported_tags(Path(sys.executable))
    await build_venv(request_for(tmp_path, backend(tmp_path, wheels)))

    # The wheel-tag probe, the interpreter version, venv, pip.
    assert len(environments) >= 4
    for environment in environments:
        assert environment is not None
        assert not set(AGENT_SECRETS) & set(environment)
        assert not [text for text in environment.values() if text in AGENT_SECRETS.values()]
