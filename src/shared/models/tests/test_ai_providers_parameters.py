"""The connection arguments a run payload's LLM and embedder config hand to a LiteLLM call.

The generation settings are `litellm_generation_kwargs` in shared/litellm_model_names.py.
"""

import pytest
from shared.models.ai_providers import EmbedderConfigData, LLMConfigData


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
