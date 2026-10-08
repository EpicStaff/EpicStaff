"""
Tests for the response_format / messages that ClassificationDecisionTableNodeSubgraph._run_json_llm
sends to litellm, per provider.

Only litellm.acompletion is mocked; its kwargs are captured and asserted on.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import StateGraph

from models.state import State
from services.graph.events import StopEvent

from src.crew.services.graph.subgraphs.classification_decision_table_node import (
    ClassificationDecisionTableNodeSubgraph,
)
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.models.graph_nodes import ClassificationDecisionTableNodeData


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string"}},
    "required": ["label"],
}
PROMPT = "Classify the following: hello world"


def make_subgraph() -> ClassificationDecisionTableNodeSubgraph:
    return ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=ClassificationDecisionTableNodeData(node_name="cdt_node"),
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        redis_service=MagicMock(),
    )


def make_llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.usage.total_tokens = 3
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 2
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


@pytest.fixture
def mock_completion():
    with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
        completion.return_value = make_llm_response('{"label": "positive"}')
        yield completion


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", " DeepSeek "])
@pytest.mark.parametrize("output_schema", [OUTPUT_SCHEMA, json.dumps(OUTPUT_SCHEMA)])
async def test_deepseek_with_schema_sends_json_object_and_schema_system_message(
    mock_completion, provider, output_schema
):
    llm = LLMData(provider=provider, config=LLMConfigData(model="deepseek-chat"))

    result, _usage = await make_subgraph()._run_json_llm(
        prompt=PROMPT, llm=llm, output_schema=output_schema
    )

    call_kwargs = mock_completion.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}
    messages = call_kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "json" in messages[0]["content"].lower()
    assert json.dumps(OUTPUT_SCHEMA) in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": PROMPT}
    assert result == {"label": "positive"}


@pytest.mark.asyncio
async def test_non_deepseek_with_schema_sends_unchanged_json_schema(mock_completion):
    llm = LLMData(provider="openai", config=LLMConfigData(model="gpt-4o-mini"))

    await make_subgraph()._run_json_llm(prompt=PROMPT, llm=llm, output_schema=OUTPUT_SCHEMA)

    call_kwargs = mock_completion.call_args.kwargs
    assert call_kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "cdt_prompt_output",
            "schema": OUTPUT_SCHEMA,
            "strict": True,
        },
    }
    assert call_kwargs["messages"] == [{"role": "user", "content": PROMPT}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider, model, expected_model",
    [
        ("google_ai", "gemini/gemini-flash-latest", "gemini/gemini-flash-latest"),
        ("google_ai", "gemini-flash-latest", "gemini/gemini-flash-latest"),
        ("novita_ai", "novita/deepseek/deepseek-r1", "novita/deepseek/deepseek-r1"),
        ("aws_sagemaker", "sagemaker/some-endpoint", "sagemaker/some-endpoint"),
        ("featherless-ai", "featherless_ai/some-model", "featherless_ai/some-model"),
        ("ollama", "ollama/mistral", "ollama/mistral"),
        ("openai", "gpt-4o-mini", "openai/gpt-4o-mini"),
        # Vendor-namespaced ids stay on the row's provider, never the vendor named in the id.
        ("groq", "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"),
        ("openrouter", "anthropic/claude-sonnet-4", "openrouter/anthropic/claude-sonnet-4"),
    ],
)
async def test_model_string_routes_to_the_row_provider(
    mock_completion, provider, model, expected_model
):
    llm = LLMData(provider=provider, config=LLMConfigData(model=model))

    await make_subgraph()._run_json_llm(prompt=PROMPT, llm=llm, output_schema=None)

    assert mock_completion.call_args.kwargs["model"] == expected_model


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", "openai"])
@pytest.mark.parametrize("output_schema", [None, {}, "", "not json"])
async def test_without_schema_sends_no_response_format_and_only_user_message(
    mock_completion, provider, output_schema
):
    llm = LLMData(provider=provider, config=LLMConfigData(model="some-model"))

    await make_subgraph()._run_json_llm(prompt=PROMPT, llm=llm, output_schema=output_schema)

    call_kwargs = mock_completion.call_args.kwargs
    assert call_kwargs["response_format"] is None
    assert call_kwargs["messages"] == [{"role": "user", "content": PROMPT}]
