"""The generation settings a run's LLM config hands to a litellm call."""

import pytest

from src.shared.litellm_model_names import litellm_generation_kwargs
from src.shared.models.ai_providers import LLMConfigData

_SAMPLING = {"temperature": 0.5, "top_p": 0.9, "top_k": 40}


def test_a_setting_no_code_names_reaches_the_kwargs():
    config = LLMConfigData(model="gpt-6", parameters={"verbosity": "low", "temperature": 0.2})

    assert litellm_generation_kwargs(config, model="gpt-6") == {"verbosity": "low", "temperature": 0.2}


def test_unset_settings_and_excluded_names_are_left_out():
    config = LLMConfigData(
        model="o3-mini", timeout=30, parameters={"seed": None, "stop": ["END"], "reasoning_effort": "low"}
    )

    assert litellm_generation_kwargs(config, model="o3-mini") == {
        "stop": ["END"],
        "reasoning_effort": "low",
        "timeout": 30,
    }
    assert litellm_generation_kwargs(config, model="o3-mini", exclude={"stop", "timeout"}) == {"reasoning_effort": "low"}


def test_transport_and_cost_fields_never_reach_the_settings():
    config = LLMConfigData(
        model="gpt-4o",
        parameters={"temperature": 0.4},
        connection={"api_base": "https://gateway.example", "api_version": "2024-10-21"},
        api_key="sk-secret",
        api_key_secret_id=5,
        extra_headers={"X-Trace": "1"},
        custom_name="Key A",
        input_cost_per_token=0.1,
        output_cost_per_token=0.2,
    )

    assert litellm_generation_kwargs(config, model="gpt-4o") == {"temperature": 0.4}


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        # Claude rejects temperature together with top_p: temperature wins.
        ({"temperature": 0.5, "top_p": 0.9}, {"temperature": 0.5}),
        # "none" sends no thinking block, so only the temperature/top_p rule applies.
        (
            {"temperature": 0.5, "top_p": 0.9, "reasoning_effort": "none"},
            {"temperature": 0.5, "reasoning_effort": "none"},
        ),
        ({"top_p": 0.9}, {"top_p": 0.9}),
        # Thinking on: top_p never, temperature only when it is 1.
        ({"temperature": 0.5, "top_p": 0.9, "reasoning_effort": "low"}, {"reasoning_effort": "low"}),
        (
            {"temperature": 1.0, "top_p": 0.9, "reasoning_effort": "minimal"},
            {"temperature": 1.0, "reasoning_effort": "minimal"},
        ),
        ({"temperature": 0.0, "reasoning_effort": "high"}, {"reasoning_effort": "high"}),
    ],
)
# A bare Claude name is routed to Anthropic too (an OpenAI row keeps it bare).
@pytest.mark.parametrize("model", ["anthropic/claude-sonnet-4-6", "claude-sonnet-4-6"])
def test_anthropic_drops_the_sampling_settings_it_rejects(model, parameters, expected):
    config = LLMConfigData(model="claude-sonnet-4-6", parameters=parameters)

    assert litellm_generation_kwargs(config, model=model) == expected


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-5-5",
        "claude-sonnet-5-5",
        "anthropic/claude-opus-4-7",
        "bedrock/us.anthropic.claude-sonnet-5-5",
        "vertex_ai/claude-opus-5-5",
        "azure_ai/claude-sonnet-5-5",
        "bedrock/us.openai.gpt-5.6-sol",
    ],
)
@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        ({**_SAMPLING, "max_tokens": 1000}, {"max_tokens": 1000}),
        # Thinking off, where the Anthropic rules would keep temperature.
        (
            {**_SAMPLING, "max_tokens": 1000, "reasoning_effort": "none"},
            {"max_tokens": 1000, "reasoning_effort": "none"},
        ),
        # litellm takes temperature 1 on these models; newer Anthropic API versions do not.
        ({"temperature": 1, "max_tokens": 1000}, {"max_tokens": 1000}),
    ],
    ids=["all", "thinking-off", "temperature-1"],
)
def test_a_model_litellm_refuses_sampling_for_gets_none_on_any_provider(model, parameters, expected):
    assert litellm_generation_kwargs(LLMConfigData(model="m", parameters=parameters), model=model) == expected


@pytest.mark.parametrize(
    "model",
    [
        "openai/gpt-4o",
        "bedrock/us.anthropic.claude-sonnet-4-6",
        "vertex_ai/gemini-2.5-pro",
        # Marked `supports_sampling_params: false`, but litellm still sends sampling to it.
        "gemini/gemini-3.5-flash-lite",
        "vertex_ai/gemini-3.8-flash",
    ],
)
def test_other_models_keep_every_sampling_setting(model):
    parameters = {**_SAMPLING, "reasoning_effort": "high"}

    assert litellm_generation_kwargs(LLMConfigData(model="m", parameters=parameters), model=model) == parameters


def test_an_excluded_reasoning_effort_does_not_count_as_thinking():
    config = LLMConfigData(model="claude-sonnet-4-6", parameters={"temperature": 0.5, "reasoning_effort": "high"})

    assert litellm_generation_kwargs(config, model="anthropic/claude-sonnet-4-6", exclude={"reasoning_effort"}) == {
        "temperature": 0.5
    }
