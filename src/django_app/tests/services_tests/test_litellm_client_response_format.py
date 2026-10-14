"""The request LiteLLMClient.stream_completion sends to litellm, per provider.

`litellm.acompletion` is the provider boundary: a stub records its kwargs and ends
the stream at once. The client reads only plain attributes off the LLM config, so
SimpleNamespace stand-ins replace ORM rows and these tests need no database.
"""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tables.services.llm_clients.base import ToolSpec
from tables.services.llm_clients.litellm_client import LiteLLMClient

OUTPUT_SCHEMA = {
    "name": "flow_assistant_reply",
    "schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
    "strict": True,
}
MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "hi"},
]


def sent_request(client: LiteLLMClient, messages: list[dict], tools: list) -> dict:
    """Stream one completion and return the kwargs litellm.acompletion received."""
    sent = {}

    async def acompletion(**kwargs):
        sent.update(kwargs)

        async def stream():
            delta = SimpleNamespace(content=None, tool_calls=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="stop")])

        return stream()

    async def consume():
        async for _event in client.stream_completion(messages, tools):
            pass

    with patch("tables.services.llm_clients.litellm_client.litellm.acompletion", new=acompletion):
        asyncio.run(consume())
    return sent


def make_llm_config(provider_name: str, model_name: str = "some-model") -> SimpleNamespace:
    model = SimpleNamespace(
        name=model_name,
        llm_provider=SimpleNamespace(name=provider_name),
        base_url=None,
        api_version=None,
        deployment_id=None,
    )
    return SimpleNamespace(
        model=model,
        temperature=None,
        max_tokens=None,
        top_p=None,
        timeout=None,
    )


@pytest.mark.parametrize("provider_name", ["deepseek", " DeepSeek "])
def test_deepseek_with_schema_sends_json_object(provider_name):
    client = LiteLLMClient(
        make_llm_config(provider_name, "deepseek-chat"),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["response_format"] == {"type": "json_object"}


def test_deepseek_with_schema_prepends_schema_system_message_without_mutating_caller():
    caller_messages = copy.deepcopy(MESSAGES)
    client = LiteLLMClient(
        make_llm_config("deepseek", "deepseek-chat"),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = sent_request(client, caller_messages, [])

    first_message = kwargs["messages"][0]
    assert first_message["role"] == "system"
    assert "json" in first_message["content"].lower()
    assert json.dumps(OUTPUT_SCHEMA["schema"]) in first_message["content"]
    assert kwargs["messages"][1:] == MESSAGES
    assert caller_messages == MESSAGES


@pytest.mark.parametrize(
    "provider_name, model_name",
    [
        ("openai", "gpt-4o"),
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("azure", "gpt-4o"),
        ("gemini", "gemini-1.5-pro"),
    ],
)
def test_non_deepseek_with_schema_sends_unchanged_json_schema(provider_name, model_name):
    client = LiteLLMClient(
        make_llm_config(provider_name, model_name),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": OUTPUT_SCHEMA,
    }
    assert kwargs["messages"] == MESSAGES


TOOLS = [
    ToolSpec(
        name="get_flow_overview",
        description="Overview of the flow.",
        parameters={"type": "object", "properties": {}},
    )
]


GROQ_MODELS = ["groq/llama-3.1-8b-instant", "groq/openai/gpt-oss-120b"]


# Groq rejects response_format together with tools whether or not the model has native
# structured outputs, so both kinds of model must get the schema through the prompt.
@pytest.mark.parametrize("model_name", GROQ_MODELS)
def test_groq_with_schema_and_tools_sends_schema_in_prompt_only(model_name):
    client = LiteLLMClient(
        make_llm_config("groq", model_name),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = sent_request(client, MESSAGES, TOOLS)

    assert "response_format" not in kwargs
    assert json.dumps(OUTPUT_SCHEMA["schema"]) in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1:] == MESSAGES
    assert kwargs["tools"][0]["function"]["name"] == "get_flow_overview"


@pytest.mark.parametrize("model_name", GROQ_MODELS)
def test_groq_with_schema_and_no_tools_sends_json_schema(model_name):
    client = LiteLLMClient(
        make_llm_config("groq", model_name),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": OUTPUT_SCHEMA,
    }
    assert kwargs["messages"] == MESSAGES


@pytest.mark.parametrize(
    "provider_name, model_name, expected_model",
    [
        ("google_ai", "gemini/gemini-flash-latest", "gemini/gemini-flash-latest"),
        ("google_ai", "gemini-flash-latest", "gemini/gemini-flash-latest"),
        ("novita_ai", "novita/deepseek/deepseek-r1", "novita/deepseek/deepseek-r1"),
        ("aws_sagemaker", "sagemaker/some-endpoint", "sagemaker/some-endpoint"),
        ("featherless-ai", "featherless_ai/some-model", "featherless_ai/some-model"),
        ("gemini", "gemini/gemini-3.5-flash", "gemini/gemini-3.5-flash"),
        ("anthropic", "claude-3-5-sonnet-20241022", "anthropic/claude-3-5-sonnet-20241022"),
        # Vendor-namespaced ids stay on the row's provider, never the vendor named in the id.
        ("groq", "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"),
        ("openrouter", "anthropic/claude-sonnet-4", "openrouter/anthropic/claude-sonnet-4"),
        ("novita_ai", "deepseek/deepseek-r1", "novita/deepseek/deepseek-r1"),
        ("cloudflare_workers_ai", "mistral/mistral-tiny", "cloudflare_workers_ai/mistral/mistral-tiny"),
    ],
)
def test_model_string_routes_to_the_row_provider(provider_name, model_name, expected_model):
    client = LiteLLMClient(make_llm_config(provider_name, model_name), api_key=None)

    assert sent_request(client, MESSAGES, [])["model"] == expected_model


@pytest.mark.parametrize("provider_name", ["deepseek", "openai"])
def test_without_schema_sends_no_response_format(provider_name):
    client = LiteLLMClient(make_llm_config(provider_name), api_key=None)

    kwargs = sent_request(client, MESSAGES, [])

    assert "response_format" not in kwargs
    assert kwargs["messages"] == MESSAGES
