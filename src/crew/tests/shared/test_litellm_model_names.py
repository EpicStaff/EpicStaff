"""The litellm model-name rules every service shares.

Lives in crew's suite, like the other `src.shared` tests here, because the shared
package has no test target of its own.
"""

import litellm
import pytest
from litellm.llms.github_copilot.authenticator import Authenticator

from src.shared.litellm_model_names import (
    litellm_call_model,
    litellm_lookup_name,
    litellm_model_capability,
    litellm_needs_cache_markers,
    litellm_refuses_sampling,
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


@pytest.mark.parametrize(
    "model, expected",
    [
        ("test-bare-model", False),
        # The map keys many models only by their bare name.
        ("anthropic/test-bare-model", False),
        # A prefixed key without the flag does not hide the bare key's flag.
        ("test-provider/test-bare-model", False),
        ("test-provider/test-prefixed-model", True),
        ("test-flagless-model", None),
        ("anthropic/test-flagless-model", None),
        ("unmapped-model", None),
        ("anthropic/unmapped-model", None),
    ],
)
def test_model_capability(monkeypatch, model, expected):
    for key, entry in {
        "test-bare-model": {"supports_forced_tool_use": False},
        "test-provider/test-bare-model": {"max_tokens": 1000},
        "test-provider/test-prefixed-model": {"supports_forced_tool_use": True},
        "test-flagless-model": {"max_tokens": 1000},
    }.items():
        monkeypatch.setitem(litellm.model_cost, key, entry)

    assert litellm_model_capability(model, "supports_forced_tool_use") is expected


@pytest.mark.parametrize(
    "model, expected",
    [
        ("anthropic/claude-sonnet-5-5", True),
        ("bedrock/us.openai.gpt-5.6-sol", True),
        # Flagged, but litellm still sends sampling to Gemini 3+.
        ("gemini/gemini-3.5-flash-lite", False),
        # Not flagged: never probed.
        ("anthropic/claude-sonnet-4-6", False),
    ],
)
@pytest.mark.parametrize("global_drop_params", [False, True])
def test_refuses_sampling_follows_litellm_whatever_its_global_drop_params(
    monkeypatch, model, expected, global_drop_params
):
    # The agent service and System One set litellm.drop_params process-wide.
    monkeypatch.setattr(litellm, "drop_params", global_drop_params)
    litellm_refuses_sampling.cache_clear()

    assert litellm_refuses_sampling(model) is expected


def test_a_flagged_model_litellm_cannot_map_is_not_refused(monkeypatch):
    monkeypatch.setitem(litellm.model_cost, "test-unknown-provider/test-model", {"supports_sampling_params": False})

    assert litellm_refuses_sampling("test-unknown-provider/test-model") is False


@pytest.mark.parametrize(
    "model, expected",
    [
        ("anthropic/claude-sonnet-5-5", True),
        ("claude-sonnet-5-5", True),
        ("bedrock/us.anthropic.claude-sonnet-5-5", True),
        ("vertex_ai/claude-sonnet-5-5", True),
        ("azure_ai/claude-sonnet-5-5", True),
        ("gpt-4o", False),
        ("gemini/gemini-2.5-pro", False),
        # Claude behind a gateway: litellm does not put Anthropic markers on these, so
        # neither do we (an OpenRouter Claude model goes without prompt caching).
        ("openrouter/anthropic/claude-sonnet-5-5", False),
        ("github_copilot/claude-sonnet-5", False),
        ("databricks/databricks-claude-sonnet-4", False),
        ("test-unknown-provider/test-model", False),
    ],
)
def test_needs_cache_markers_follows_litellm(monkeypatch, model, expected):
    # A GitHub Copilot login waits for a human; pytest.fail escapes the helper's
    # `except Exception`, so an attempted login fails the test instead of hanging it.
    for method in ("get_access_token", "get_api_key"):
        monkeypatch.setattr(Authenticator, method, lambda self: pytest.fail("login attempted"))
    litellm_needs_cache_markers.cache_clear()

    assert litellm_needs_cache_markers(model) is expected
