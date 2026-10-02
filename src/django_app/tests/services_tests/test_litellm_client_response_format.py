"""Response-format tests for LiteLLMClient._build_kwargs.

`_build_kwargs` reads only plain attributes off the LLM config, so SimpleNamespace
stand-ins replace ORM rows and these tests need no database.
"""

import copy
import json
from types import SimpleNamespace

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

    kwargs = client._build_kwargs(MESSAGES, [])

    assert kwargs["response_format"] == {"type": "json_object"}


def test_deepseek_with_schema_prepends_schema_system_message_without_mutating_caller():
    caller_messages = copy.deepcopy(MESSAGES)
    client = LiteLLMClient(
        make_llm_config("deepseek", "deepseek-chat"),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = client._build_kwargs(caller_messages, [])

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

    kwargs = client._build_kwargs(MESSAGES, [])

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


# The Groq cases below read native structured-output support from litellm's bundled model
# catalog; a litellm upgrade that changes these models' capabilities flips them.
def test_groq_model_without_native_schema_and_tools_sends_schema_in_prompt_only():
    client = LiteLLMClient(
        make_llm_config("groq", "groq/llama-3.1-8b-instant"),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = client._build_kwargs(MESSAGES, TOOLS)

    assert "response_format" not in kwargs
    assert json.dumps(OUTPUT_SCHEMA["schema"]) in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1:] == MESSAGES
    assert kwargs["tools"][0]["function"]["name"] == "get_flow_overview"


def test_groq_model_with_native_schema_sends_json_schema():
    client = LiteLLMClient(
        make_llm_config("groq", "groq/openai/gpt-oss-120b"),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = client._build_kwargs(MESSAGES, TOOLS)

    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": OUTPUT_SCHEMA,
    }
    assert kwargs["messages"] == MESSAGES


def test_groq_model_without_native_schema_and_no_tools_sends_json_schema():
    client = LiteLLMClient(
        make_llm_config("groq", "groq/llama-3.1-8b-instant"),
        api_key=None,
        output_schema=OUTPUT_SCHEMA,
    )

    kwargs = client._build_kwargs(MESSAGES, [])

    assert kwargs["response_format"]["type"] == "json_schema"


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

    assert client._build_kwargs(MESSAGES, [])["model"] == expected_model


@pytest.mark.parametrize("provider_name", ["deepseek", "openai"])
def test_without_schema_sends_no_response_format(provider_name):
    client = LiteLLMClient(make_llm_config(provider_name), api_key=None)

    kwargs = client._build_kwargs(MESSAGES, [])

    assert "response_format" not in kwargs
    assert kwargs["messages"] == MESSAGES
