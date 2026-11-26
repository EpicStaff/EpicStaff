"""What a run payload's LLM and embedder config hand to a LiteLLM call."""

import pytest
from shared.models.ai_providers import EmbedderConfigData, LLMConfigData


def test_a_setting_no_code_names_reaches_the_kwargs():
    config = LLMConfigData(model="gpt-6", parameters={"verbosity": "low", "temperature": 0.2})

    assert config.to_litellm_kwargs(provider="openai") == {"verbosity": "low", "temperature": 0.2}


def test_unset_settings_and_excluded_names_are_left_out():
    config = LLMConfigData(
        model="o3-mini", timeout=30, parameters={"seed": None, "stop": ["END"], "reasoning_effort": "low"}
    )

    assert config.to_litellm_kwargs(provider="openai") == {
        "stop": ["END"],
        "reasoning_effort": "low",
        "timeout": 30,
    }
    assert config.to_litellm_kwargs(provider="openai", exclude={"stop", "timeout"}) == {"reasoning_effort": "low"}


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

    assert config.to_litellm_kwargs(provider="openai") == {"temperature": 0.4}


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
def test_anthropic_drops_the_sampling_settings_it_rejects(parameters, expected):
    config = LLMConfigData(model="claude-sonnet-4-6", parameters=parameters)

    assert config.to_litellm_kwargs(provider="anthropic") == expected


@pytest.mark.parametrize("provider", ["openai", "bedrock", "vertex_ai"])
def test_other_providers_keep_every_sampling_setting(provider):
    parameters = {"temperature": 0.5, "top_p": 0.9, "reasoning_effort": "high"}

    assert LLMConfigData(model="m", parameters=parameters).to_litellm_kwargs(provider=provider) == parameters


def test_an_excluded_reasoning_effort_does_not_count_as_thinking():
    config = LLMConfigData(model="claude-sonnet-4-6", parameters={"temperature": 0.5, "reasoning_effort": "high"})

    assert config.to_litellm_kwargs(provider="anthropic", exclude={"reasoning_effort"}) == {"temperature": 0.5}


@pytest.mark.parametrize("config_class", [LLMConfigData, EmbedderConfigData])
@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, {}),
        ({"api_key": "sk-1"}, {"api_key": "sk-1"}),
        (
            {"api_key": "secret-key", "main_secret_argument": "aws_secret_access_key"},
            {"aws_secret_access_key": "secret-key"},
        ),
        # Without a resolved main secret, the argument is not sent at all.
        ({"main_secret_argument": "vertex_credentials"}, {}),
        (
            {
                "api_key": "sk-1",
                "connection": {"api_base": "https://gateway.example", "aws_region_name": "", "api_version": "v1"},
            },
            {"api_base": "https://gateway.example", "api_version": "v1", "api_key": "sk-1"},
        ),
        # litellm sends any call carrying a deployment_id to Azure; an Azure config names
        # its deployment in the model string instead.
        ({"connection": {"deployment_id": "my-deployment", "api_base": "https://x"}}, {"api_base": "https://x"}),
    ],
    ids=["nothing", "api-key", "other-argument", "no-secret", "connection", "no-deployment-id"],
)
def test_connection_kwargs_carry_the_connection_and_the_main_secret(config_class, fields, expected):
    assert config_class(model="m", **fields).connection_kwargs() == expected


def test_the_main_secret_argument_survives_the_wire():
    config = LLMConfigData(model="m", main_secret_argument="vertex_credentials", connection={"vertex_project": "p"})

    assert LLMConfigData.model_validate_json(config.model_dump_json()) == config


@pytest.mark.parametrize("config_class", [LLMConfigData, EmbedderConfigData])
def test_the_repr_hides_resolved_secrets(config_class):
    config = config_class(model="m", connection={"aws_access_key_id": "AKIA-resolved"}, api_key="sk-resolved")

    assert "AKIA-resolved" not in repr(config)
    assert "sk-resolved" not in repr(config)
