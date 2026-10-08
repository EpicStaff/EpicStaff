"""LLM resources: quickstart bundle, a model pointing at mock-llm, and an LLM config on it.

quickstart -> mock_llm_model -> e2e_llm_config
"""

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from helpers.api import ApiClient, page_results
from helpers.bootstrap import unique_suffix
from helpers.mock_llm import MockLlmClient
from helpers.redaction import register_secret

# The provider key never leaves the stack: every model the suite uses points at mock-llm.
QUICKSTART_API_KEY = register_secret("sk-e2e-dummy")
MOCK_LLM_BASE_URL_IN_STACK = "http://mock-llm:8080/v1"


@dataclass(frozen=True)
class Quickstart:
    """`POST /api/quickstart/` body and the ids it created (one Secret backs both configs)."""

    body: dict
    secret_id: int
    llm_config_id: int
    embedding_config_id: int


@pytest.fixture(scope="session")
def mock_llm() -> Iterator[MockLlmClient]:
    client = MockLlmClient()
    yield client
    client.close()


@pytest.fixture(scope="session")
def quickstart(user_client: ApiClient) -> Quickstart:
    body = user_client.post(
        "/api/quickstart/", json={"provider": "openai", "api_key": QUICKSTART_API_KEY}
    ).json()
    configs = body["configs"]
    return Quickstart(
        body=body,
        secret_id=configs["llm_config"]["api_key_secret_id"],
        llm_config_id=configs["llm_config"]["id"],
        embedding_config_id=configs["embedding_config"]["id"],
    )


@pytest.fixture(scope="session")
def openai_provider_id(user_client: ApiClient) -> int:
    [provider] = page_results(user_client.get("/api/providers/", params={"name": "openai"}).json())
    return provider["id"]


@pytest.fixture(scope="session")
def mock_llm_model(user_client: ApiClient, openai_provider_id: int) -> dict:
    """A custom model on the openai provider whose base URL is mock-llm.

    The agent reads the base URL from the model; `LLMConfig.base_url` is not used.
    """
    return user_client.post(
        "/api/llm-models/",
        json={
            "name": f"mock-gpt-{unique_suffix()}",
            "llm_provider": openai_provider_id,
            "base_url": MOCK_LLM_BASE_URL_IN_STACK,
        },
        expect=201,
    ).json()


@pytest.fixture(scope="session")
def e2e_llm_config(user_client: ApiClient, mock_llm_model: dict, quickstart: Quickstart) -> dict:
    """LLM config on the mock model, bound to the quickstart Secret (needs `secrets:use`)."""
    return user_client.post(
        "/api/llm-configs/",
        json={
            "custom_name": f"e2e-llm-{unique_suffix()}",
            "model": mock_llm_model["id"],
            "api_key_secret_id": quickstart.secret_id,
            "temperature": 0,
            "max_tokens": 1000,
        },
        expect=201,
    ).json()
