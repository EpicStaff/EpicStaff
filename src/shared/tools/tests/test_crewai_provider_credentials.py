"""Provider credentials of the crewai tools come from the tool configuration.

Each credential is declared `"input_type": "user_input"` in args_schema.json, so
the agent never sees it, and main() reads it from the module globals the
sandbox seeds from the configuration. A value the agent passes as a stray
kwarg is ignored, a missing one is reported as an error string, and a provider
error never echoes the secret back to the agent.

The providers' SDKs are replaced by fakes that record the credentials they are
built with. Several SDKs are not installed in the test environment (each tool
gets its own venv in the sandbox), so the fakes are installed into sys.modules
before the tool is loaded.
"""

import json
import socket
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Callable

import pytest
import requests

from conftest import TOOLS_ROOT, FakeResponse, load_tool_main

SRC_DIR = TOOLS_ROOT.parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shared.models.variable_conversion import args_schema_to_variables  # noqa: E402

SECRET = "secret-from-config"
AGENT_VALUE = "value-the-agent-made-up"
MISSING_SETTING = "is required but not configured"


class ProviderCalls:
    """What the fake SDKs were given; `fail` makes their operation raise an
    error whose message carries every credential, like a careless SDK might."""

    def __init__(self):
        self.credentials: list[tuple] = []
        self.fail = False

    def record(self, *credentials):
        self.credentials.append(credentials)

    def operation(self, result):
        if self.fail:
            raise ConnectionError(f"provider failed, credentials={self.credentials}")
        return result


def _module(monkeypatch, name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _fake_openai(monkeypatch, calls: ProviderCalls):
    import openai

    def client(api_key):
        calls.record("openai", api_key)
        content = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="described"))])
        image = SimpleNamespace(data=[SimpleNamespace(url="https://img/1.png", revised_prompt="a cube")])
        embedding = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: calls.operation(content))),
            images=SimpleNamespace(generate=lambda **kwargs: calls.operation(image)),
            embeddings=SimpleNamespace(create=lambda **kwargs: calls.operation(embedding)),
        )

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(openai, "Client", client)


def _fake_jina(monkeypatch, calls: ProviderCalls):
    # Every host resolves to a public address, so the SSRF guard passes offline.
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))])

    def get(url, headers=None, timeout=None, allow_redirects=True):
        calls.record("jina", headers["Authorization"])
        return calls.operation(FakeResponse(text="markdown content"))

    monkeypatch.setattr(requests, "get", get)


def _fake_scrapfly(monkeypatch, calls: ProviderCalls):
    class ScrapflyClient:
        def __init__(self, key):
            calls.record("scrapfly", key)

        def scrape(self, config):
            return calls.operation(SimpleNamespace(scrape_result={"content": "page content"}))

    _module(monkeypatch, "scrapfly", ScrapflyClient=ScrapflyClient, ScrapeConfig=lambda url, **kwargs: url)


def _fake_qdrant(monkeypatch, calls: ProviderCalls):
    _fake_openai(monkeypatch, calls)

    class QdrantClient:
        def __init__(self, url, api_key):
            calls.record("qdrant", url, api_key)

        def query_points(self, **kwargs):
            point = SimpleNamespace(payload={"text": "found"}, score=0.9)
            return calls.operation([("points", [point])])

    _module(monkeypatch, "qdrant_client", QdrantClient=QdrantClient)
    _module(monkeypatch, "qdrant_client.http")
    _module(
        monkeypatch,
        "qdrant_client.http.models",
        Filter=SimpleNamespace,
        FieldCondition=SimpleNamespace,
        MatchValue=SimpleNamespace,
    )


def _fake_couchbase(monkeypatch, calls: ProviderCalls):
    class Cluster:
        def __init__(self, connection_string, authenticator):
            calls.record("couchbase", connection_string, *authenticator)

        def bucket(self, name):
            # The tool's embed() is a stub that raises before scope.search runs, so the scope is never used.
            return SimpleNamespace(scope=lambda name: None)

    _module(monkeypatch, "couchbase")
    _module(monkeypatch, "couchbase.search", SearchRequest=SimpleNamespace(create=lambda request: request))
    _module(monkeypatch, "couchbase.cluster", Cluster=Cluster)
    _module(monkeypatch, "couchbase.options", SearchOptions=SimpleNamespace)
    _module(monkeypatch, "couchbase.auth", PasswordAuthenticator=lambda username, password: (username, password))
    _module(
        monkeypatch,
        "couchbase.vector_search",
        VectorQuery=lambda *args: args,
        VectorSearch=SimpleNamespace(from_vector_query=lambda query: query),
    )


def _fake_mongodb(monkeypatch, calls: ProviderCalls):
    _fake_openai(monkeypatch, calls)

    class MongoClient:
        def __init__(self, connection_string, driver):
            calls.record("mongodb", connection_string)

        def __getitem__(self, database_name):
            collection = SimpleNamespace(aggregate=lambda pipeline: calls.operation([{"text": "found"}]))
            return {"docs": collection}

    _module(monkeypatch, "pymongo", MongoClient=MongoClient)
    _module(monkeypatch, "pymongo.driver_info", DriverInfo=lambda **kwargs: None)
    _module(monkeypatch, "bson")
    _module(monkeypatch, "bson.json_util", dumps=json.dumps)
    sys.modules["bson"].json_util = sys.modules["bson.json_util"]


@dataclass
class CredentialCase:
    tool_dir: str
    config: dict
    fake_provider: Callable
    call: Callable
    # Exactly what the providers must receive when `config` is set.
    expected_credentials: list[tuple]
    provider_errors_are_scrubbed: bool = True


CASES = [
    CredentialCase(
        "crewai_jina_scraper_website_tool",
        {"api_key": SECRET},
        _fake_jina,
        lambda tool: tool.main(website_url="https://example.com/page", api_key=AGENT_VALUE),
        [("jina", f"Bearer {SECRET}")],
        # Jina gets the key in a header; requests' errors carry the URL, never
        # headers, so the tool hands them to the agent as they are.
        provider_errors_are_scrubbed=False,
    ),
    CredentialCase(
        "crewai_dalle_tool",
        {"api_key": SECRET},
        _fake_openai,
        lambda tool: tool.main(image_description="a cube", api_key=AGENT_VALUE),
        [("openai", SECRET)],
    ),
    CredentialCase(
        "crewai_scrapfly_scrape_website_tool",
        {"api_key": SECRET},
        _fake_scrapfly,
        lambda tool: tool.main(url="https://example.com", api_key=AGENT_VALUE),
        [("scrapfly", SECRET)],
    ),
    CredentialCase(
        "crewai_ocr_tool",
        {"openai_api_key": SECRET},
        _fake_openai,
        lambda tool: tool.main(image_path_url="https://example.com/a.png", openai_api_key=AGENT_VALUE),
        [("openai", SECRET)],
    ),
    CredentialCase(
        "crewai_vision_tool",
        {"openai_api_key": SECRET},
        _fake_openai,
        lambda tool: tool.main(image_path_url="https://example.com/a.png", openai_api_key=AGENT_VALUE),
        [("openai", SECRET)],
    ),
    CredentialCase(
        "crewai_qdrant_search_tool",
        {"qdrant_url": "https://qdrant.internal", "qdrant_api_key": SECRET, "openai_api_key": SECRET},
        _fake_qdrant,
        lambda tool: tool.main(
            query="vectors", collection_name="docs", qdrant_url=AGENT_VALUE, openai_api_key=AGENT_VALUE
        ),
        [("qdrant", "https://qdrant.internal", SECRET), ("openai", SECRET)],
    ),
    CredentialCase(
        "crewai_couchbase_tool",
        {"connection_string": "couchbase://db.internal", "username": "reader", "password": SECRET},
        _fake_couchbase,
        lambda tool: tool.main(
            query="vectors",
            bucket_name="bucket",
            scope_name="scope",
            collection_name="docs",
            index_name="index",
            password=AGENT_VALUE,
        ),
        [("couchbase", "couchbase://db.internal", "reader", SECRET)],
    ),
    CredentialCase(
        "crewai_mongodb_vector_search_tool",
        {"connection_string": "mongodb://db.internal", "openai_api_key": SECRET},
        _fake_mongodb,
        lambda tool: tool.main(
            query="vectors", database_name="db", collection_name="docs", connection_string=AGENT_VALUE
        ),
        [("openai", SECRET), ("mongodb", "mongodb://db.internal")],
    ),
]
EACH_CASE = pytest.mark.parametrize("case", CASES, ids=[case.tool_dir for case in CASES])


def _load(case: CredentialCase, monkeypatch, config: dict) -> tuple[ModuleType, ProviderCalls]:
    calls = ProviderCalls()
    case.fake_provider(monkeypatch, calls)
    tool = load_tool_main(case.tool_dir)
    for name, value in config.items():
        setattr(tool, name, value)
    return tool, calls


@EACH_CASE
def test_credentials_are_configuration_fields_the_agent_never_sees(case):
    schema = json.loads((TOOLS_ROOT / case.tool_dir / "args_schema.json").read_text())

    input_types = {variable["name"]: variable["input_type"] for variable in args_schema_to_variables(schema)}

    assert {name: input_types.get(name) for name in case.config} == dict.fromkeys(case.config, "user_input")


@EACH_CASE
def test_configured_credentials_reach_the_provider_and_agent_values_are_ignored(case, monkeypatch):
    tool, calls = _load(case, monkeypatch, case.config)

    case.call(tool)

    assert calls.credentials == case.expected_credentials


@EACH_CASE
def test_missing_credentials_are_reported_without_calling_the_provider(case, monkeypatch):
    tool, calls = _load(case, monkeypatch, {})

    result = case.call(tool)

    assert MISSING_SETTING in str(result)
    assert calls.credentials == []


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case.provider_errors_are_scrubbed],
    ids=[case.tool_dir for case in CASES if case.provider_errors_are_scrubbed],
)
def test_provider_errors_do_not_echo_the_credentials(case, monkeypatch):
    tool, calls = _load(case, monkeypatch, case.config)
    calls.fail = True

    result = case.call(tool)

    assert result is not None
    assert SECRET not in str(result)
