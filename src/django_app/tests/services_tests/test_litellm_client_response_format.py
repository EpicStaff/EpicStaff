"""The request LiteLLMClient.stream_completion sends to litellm, per provider.

`litellm.acompletion` is the provider boundary: a stub records its kwargs and ends
the stream at once. The client takes an LLMConfigData, not an ORM row, so these
tests need no database.
"""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.shared.models import LLMConfigData
from tables.services.llm_clients.base import ToolSpec, UnsupportedLLMProviderError
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


def make_client(
    provider_name: str | None,
    model_name: str = "some-model",
    output_schema: dict | None = None,
    **config_fields,
) -> LiteLLMClient:
    return LiteLLMClient(
        LLMConfigData(model=model_name, **config_fields),
        provider_name=provider_name,
        api_key=None,
        output_schema=output_schema,
    )


@pytest.mark.parametrize("provider_name", ["deepseek", " DeepSeek "])
def test_deepseek_with_schema_sends_json_object(provider_name):
    client = make_client(provider_name, "deepseek-chat", output_schema=OUTPUT_SCHEMA)

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["response_format"] == {"type": "json_object"}


def test_deepseek_with_schema_prepends_schema_system_message_without_mutating_caller():
    caller_messages = copy.deepcopy(MESSAGES)
    client = make_client("deepseek", "deepseek-chat", output_schema=OUTPUT_SCHEMA)

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
    client = make_client(provider_name, model_name, output_schema=OUTPUT_SCHEMA)

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
    client = make_client("groq", model_name, output_schema=OUTPUT_SCHEMA)

    kwargs = sent_request(client, MESSAGES, TOOLS)

    assert "response_format" not in kwargs
    assert json.dumps(OUTPUT_SCHEMA["schema"]) in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1:] == MESSAGES
    assert kwargs["tools"][0]["function"]["name"] == "get_flow_overview"


@pytest.mark.parametrize("model_name", GROQ_MODELS)
def test_groq_with_schema_and_no_tools_sends_json_schema(model_name):
    client = make_client("groq", model_name, output_schema=OUTPUT_SCHEMA)

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": OUTPUT_SCHEMA,
    }
    assert kwargs["messages"] == MESSAGES


# Gemini rejects a JSON response mime type together with function calling, and a
# google_ai row only matches the rule through the provider litellm routes it to.
GEMINI_ROWS = [
    ("google_ai", "gemini-2.5-flash"),
    ("google_ai", "gemini/gemini-2.5-flash"),
    ("gemini", "gemini-2.5-flash"),
]


@pytest.mark.parametrize("provider_name, model_name", GEMINI_ROWS)
def test_gemini_with_schema_and_tools_sends_schema_in_prompt_only(provider_name, model_name):
    client = make_client(provider_name, model_name, output_schema=OUTPUT_SCHEMA)

    kwargs = sent_request(client, MESSAGES, TOOLS)

    assert "response_format" not in kwargs
    assert json.dumps(OUTPUT_SCHEMA["schema"]) in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1:] == MESSAGES
    assert kwargs["tools"][0]["function"]["name"] == "get_flow_overview"


@pytest.mark.parametrize("provider_name, model_name", GEMINI_ROWS)
def test_gemini_with_schema_and_no_tools_sends_json_schema(provider_name, model_name):
    client = make_client(provider_name, model_name, output_schema=OUTPUT_SCHEMA)

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": OUTPUT_SCHEMA,
    }
    assert kwargs["messages"] == MESSAGES


# A row without a provider names it only in the model prefix, so the format rules must
# follow the provider litellm routes to, not the row's name.
@pytest.mark.parametrize(
    "model_name, tools, expected_response_format",
    [
        ("deepseek/deepseek-chat", [], {"type": "json_object"}),
        ("groq/llama-3.1-8b-instant", TOOLS, None),
        ("gemini/gemini-2.5-flash", TOOLS, None),
    ],
)
def test_response_format_follows_the_routed_provider(model_name, tools, expected_response_format):
    client = make_client(None, model_name, output_schema=OUTPUT_SCHEMA)

    kwargs = sent_request(client, MESSAGES, tools)

    assert kwargs.get("response_format") == expected_response_format
    assert json.dumps(OUTPUT_SCHEMA["schema"]) in kwargs["messages"][0]["content"]


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
    client = make_client(provider_name, model_name)

    assert sent_request(client, MESSAGES, [])["model"] == expected_model


@pytest.mark.parametrize("provider_name", ["deepseek", "openai"])
def test_without_schema_sends_no_response_format(provider_name):
    client = make_client(provider_name)

    kwargs = sent_request(client, MESSAGES, [])

    assert "response_format" not in kwargs
    assert kwargs["messages"] == MESSAGES


def test_generation_params_except_stop_reach_the_request():
    client = make_client(
        "openai",
        "o3-mini",
        reasoning_effort="high",
        stop=["END"],
        logit_bias={50256: -100.0},
        temperature=0.2,
        seed=7,
    )

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["reasoning_effort"] == "high"
    # The config's stop sequences are agent-oriented and could cut the JSON reply.
    assert "stop" not in kwargs
    assert kwargs["logit_bias"] == {50256: -100.0}
    assert kwargs["temperature"] == 0.2
    assert kwargs["seed"] == 7


@pytest.mark.parametrize(
    "provider_name, model_name, expected_sampling",
    [
        # Anthropic rejects temperature != 1 and top_p while thinking is on.
        ("anthropic", "claude-sonnet-4-6", {}),
        # An OpenAI row keeps the name bare, and litellm still routes it to Anthropic.
        ("openai", "claude-sonnet-4-6", {}),
        (None, "claude-sonnet-4-6", {}),
        ("openai", "gpt-4o", {"temperature": 0.5, "top_p": 0.9}),
        # A model litellm does not know keeps the provider its string names.
        ("openai", "not-a-known-model", {"temperature": 0.5, "top_p": 0.9}),
    ],
)
def test_sampling_params_follow_the_routed_provider(provider_name, model_name, expected_sampling):
    client = make_client(
        provider_name, model_name, temperature=0.5, top_p=0.9, reasoning_effort="high"
    )

    kwargs = sent_request(client, MESSAGES, [])

    assert {key: kwargs[key] for key in ("temperature", "top_p") if key in kwargs} == expected_sampling
    assert kwargs["reasoning_effort"] == "high"


def test_unset_reasoning_effort_sends_no_key():
    kwargs = sent_request(make_client("openai", "gpt-4o"), MESSAGES, [])

    assert "reasoning_effort" not in kwargs
    assert "stop" not in kwargs
    assert "logit_bias" not in kwargs


def test_azure_model_string_uses_the_deployment_id():
    client = make_client("azure", "o3-mini", deployment_id="my-o3-deployment")

    assert sent_request(client, MESSAGES, [])["model"] == "azure/my-o3-deployment"


def test_transport_fields_come_from_the_config():
    client = make_client(
        "azure",
        "gpt-4o",
        base_url="https://example.openai.azure.com",
        api_version="2024-10-21",
        extra_headers={"X-Trace": "1"},
    )

    kwargs = sent_request(client, MESSAGES, [])

    assert kwargs["base_url"] == "https://example.openai.azure.com"
    assert kwargs["api_version"] == "2024-10-21"
    assert kwargs["extra_headers"] == {"X-Trace": "1"}


def test_provider_less_model_uses_the_bare_model_name():
    assert sent_request(make_client(None, "gpt-4o"), MESSAGES, [])["model"] == "gpt-4o"


def test_empty_model_name_raises_unsupported_provider():
    with pytest.raises(UnsupportedLLMProviderError):
        make_client("openai", "  ")
