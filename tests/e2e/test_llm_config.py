"""Quickstart, a custom model pointing at mock-llm, and an LLM config bound to the quickstart Secret."""

from fixtures.llm import MOCK_LLM_BASE_URL_IN_STACK, Quickstart
from helpers.api import ApiClient


def test_quickstart_creates_a_secret_backed_bundle(user_client: ApiClient, quickstart: Quickstart) -> None:
    configs = quickstart.body["configs"]
    # QuickstartService names the bundle `quickstart_<provider>`, `_N` added on repeats.
    assert quickstart.body["config_name"].startswith("quickstart_openai")
    assert isinstance(quickstart.llm_config_id, int)
    assert isinstance(quickstart.embedding_config_id, int)
    assert isinstance(quickstart.secret_id, int)
    # One Secret backs every config of the bundle.
    assert configs["embedding_config"]["api_key_secret_id"] == quickstart.secret_id

    embedding_model_id = configs["embedding_config"]["model"]
    embedding_model = user_client.get(f"/api/embedding-models/{embedding_model_id}/").json()
    assert embedding_model["name"] == "text-embedding-3-small"


def test_openai_provider_is_listed(user_client: ApiClient, openai_provider_id: int) -> None:
    provider = user_client.get(f"/api/providers/{openai_provider_id}/").json()
    assert provider["name"] == "openai"


def test_custom_model_points_at_mock_llm(mock_llm_model: dict, openai_provider_id: int) -> None:
    assert mock_llm_model["name"].startswith("mock-gpt-")
    assert mock_llm_model["llm_provider"] == openai_provider_id
    assert mock_llm_model["base_url"] == MOCK_LLM_BASE_URL_IN_STACK


def test_llm_config_binds_the_quickstart_secret(
    e2e_llm_config: dict, mock_llm_model: dict, quickstart: Quickstart
) -> None:
    assert e2e_llm_config["custom_name"].startswith("e2e-llm-")
    assert e2e_llm_config["model"] == mock_llm_model["id"]
    assert e2e_llm_config["api_key_secret_id"] == quickstart.secret_id
    assert e2e_llm_config["temperature"] == 0
    assert e2e_llm_config["max_tokens"] == 1000
