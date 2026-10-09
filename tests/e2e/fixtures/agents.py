"""Agent resources: a surface exposing the RAG collection, and an agent on the mock LLM.

naive_rag -> knowledge_surface        e2e_llm_config -> e2e_agent
"""

import pytest

from helpers.api import ApiClient
from helpers.bootstrap import unique_suffix

AGENT_INSTRUCTION = "Always call the knowledge search tool and answer only from it."
NAIVE_SEARCH_CONFIG = {"search_limit": 3, "similarity_threshold": "0.20"}


@pytest.fixture(scope="session")
def knowledge_surface(user_client: ApiClient, rag_collection: dict, naive_rag: dict) -> dict:
    """Surface with the collection as knowledge. Valid only once the collection has a naive RAG."""
    return user_client.post(
        "/api/surfaces/",
        json={
            "name": f"e2e-kb-surface-{unique_suffix()}",
            "knowledge": [
                {
                    "collection": rag_collection["collection_id"],
                    "naive_search_config": NAIVE_SEARCH_CONFIG,
                }
            ],
        },
        expect=201,
    ).json()


@pytest.fixture(scope="session")
def e2e_agent(user_client: ApiClient, e2e_llm_config: dict) -> dict:
    return user_client.post(
        "/api/agent-definitions/",
        json={
            "name": f"e2e-agent-{unique_suffix()}",
            "instruction_list": [{"name": "main", "content": AGENT_INSTRUCTION}],
            "llm_config": e2e_llm_config["id"],
            "max_execution_time": 120,
        },
        expect=201,
    ).json()
