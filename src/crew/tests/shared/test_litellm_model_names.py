"""The litellm model-name rules every service shares.

Lives in crew's suite, like the other `src.shared` tests here, because the shared
package has no test target of its own.
"""

import pytest

from src.shared.litellm_model_names import (
    litellm_call_model,
    litellm_lookup_name,
    litellm_routed_provider,
)


@pytest.mark.parametrize(
    "provider_name, model_name, expected",
    [
        (None, "gpt-4o", "gpt-4o"),
        ("", "gpt-4o", "gpt-4o"),
        (" OpenAI ", " gpt-4o ", "openai/gpt-4o"),
        ("ollama", "ollama/mistral", "ollama/mistral"),
        ("anthropic", "claude-3-5-sonnet-20241022", "anthropic/claude-3-5-sonnet-20241022"),
        # Only the row's own provider counts, never the vendor named in the model id.
        ("groq", "openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"),
        ("openrouter", "anthropic/claude-sonnet-4", "openrouter/anthropic/claude-sonnet-4"),
        ("google_ai", "my-custom-model", "gemini/my-custom-model"),
        ("google_ai", "gemini/gemini-2.5-pro", "gemini/gemini-2.5-pro"),
        ("novita_ai", "deepseek/deepseek-r1", "novita/deepseek/deepseek-r1"),
        ("featherless-ai", "featherless_ai/some-model", "featherless_ai/some-model"),
        # Azure is looked up by model name, never by deployment id.
        ("azure", "o3-mini", "azure/o3-mini"),
    ],
)
def test_lookup_name(provider_name, model_name, expected):
    assert litellm_lookup_name(provider_name, model_name) == expected


@pytest.mark.parametrize(
    "provider_name, model_name, deployment_id, expected",
    [
        (None, "gpt-4o", None, "gpt-4o"),
        ("", " gpt-4o ", None, "gpt-4o"),
        # An OpenAI row keeps its name as stored; litellm routes it to the right vendor.
        ("openai", "gpt-4o", None, "gpt-4o"),
        (" OpenAI ", " claude-sonnet-4-6 ", None, "claude-sonnet-4-6"),
        ("openai", "anthropic/claude-sonnet-4-6", None, "anthropic/claude-sonnet-4-6"),
        ("openai", "openai/gpt-4o", None, "openai/gpt-4o"),
        # A bare name litellm does not know (a self-hosted OpenAI-compatible model) is OpenAI's.
        ("openai", "my-llama", None, "openai/my-llama"),
        ("openai", " my-llama ", None, "openai/my-llama"),
        ("groq", "openai/gpt-oss-120b", None, "groq/openai/gpt-oss-120b"),
        ("google_ai", "my-custom-model", None, "gemini/my-custom-model"),
        ("google_ai", "gemini/gemini-2.5-pro", None, "gemini/gemini-2.5-pro"),
        ("azure", "o3-mini", "my-o3-deployment", "azure/my-o3-deployment"),
        ("azure_openai", "o3-mini", " my-o3-deployment ", "azure/my-o3-deployment"),
        ("azure", "o3-mini", None, "azure/o3-mini"),
        ("azure", "o3-mini", "", "azure/o3-mini"),
        # A deployment id means nothing outside Azure.
        ("groq", "llama-3.1-8b-instant", "ignored", "groq/llama-3.1-8b-instant"),
    ],
)
def test_call_model(provider_name, model_name, deployment_id, expected):
    assert litellm_call_model(provider_name, model_name, deployment_id) == expected


@pytest.mark.parametrize(
    "model, expected",
    [
        ("gpt-4o", "openai"),
        ("claude-sonnet-4-6", "anthropic"),
        ("anthropic/claude-sonnet-4-6", "anthropic"),
        ("groq/openai/gpt-oss-120b", "groq"),
        ("azure/my-o3-deployment", "azure"),
        # litellm does not know these: the prefix decides, and a bare name is OpenAI's.
        ("my_gateway/some-model", "my_gateway"),
        ("my-llama", "openai"),
    ],
)
def test_routed_provider(model, expected):
    assert litellm_routed_provider(model) == expected
