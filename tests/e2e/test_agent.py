"""Knowledge surface and agent definition on the mock LLM; the legacy `instructions` field is refused."""

from fixtures.agents import AGENT_INSTRUCTION, NAIVE_SEARCH_CONFIG
from helpers.api import ApiClient, assert_error
from helpers.bootstrap import unique_suffix


def test_surface_exposes_the_collection(knowledge_surface: dict, rag_collection: dict) -> None:
    [knowledge] = knowledge_surface["knowledge"]
    assert knowledge["collection"] == rag_collection["collection_id"]
    search = knowledge["naive_search_config"]
    assert search["search_limit"] == NAIVE_SEARCH_CONFIG["search_limit"]
    assert float(search["similarity_threshold"]) == float(NAIVE_SEARCH_CONFIG["similarity_threshold"])


def test_agent_is_created_on_the_mock_llm_config(e2e_agent: dict, e2e_llm_config: dict) -> None:
    assert e2e_agent["llm_config"] == e2e_llm_config["id"]
    assert e2e_agent["instruction_list"] == [{"name": "main", "content": AGENT_INSTRUCTION}]
    assert e2e_agent["max_execution_time"] == 120


def test_legacy_instructions_field_is_rejected(user_client: ApiClient, e2e_llm_config: dict) -> None:
    response = user_client.post(
        "/api/agent-definitions/",
        json={
            "name": f"e2e-legacy-agent-{unique_suffix()}",
            "instructions": "Legacy single instruction text.",
            "llm_config": e2e_llm_config["id"],
        },
        expect=None,
    )
    envelope = assert_error(response, 400, "invalid")
    # The flattened message names the offending field first (`instructions: ...`).
    assert envelope["message"].startswith("instructions"), envelope
