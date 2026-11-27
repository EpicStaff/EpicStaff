from unittest.mock import AsyncMock, patch

from graphrag_llm.completion import lite_llm_completion
from graphrag_llm.config import ModelConfig
from graphrag_llm.embedding import lite_llm_embedding
import pytest
from infrastructure.graphrag.model_access import apply_request_access, completion_call_arguments


def _model_config(**overrides) -> ModelConfig:
    # Built as the mapper builds it: placeholders where each request supplies the values.
    return ModelConfig(
        **{
            "model_provider": "openai",
            "model": "m",
            "api_key": "set-by-request",
            "api_base": "set-by-request",
            **overrides,
        }
    )


def _litellm_arguments(model_config: ModelConfig) -> dict:
    """The keyword arguments graphrag_llm passes to litellm.completion for `model_config`."""
    completion, _ = lite_llm_completion._create_base_completions(
        model_config=model_config,
        drop_unsupported_params=True,
        azure_cognitive_services_audience="",
    )
    with patch.object(lite_llm_completion.litellm, "completion") as litellm_completion:
        litellm_completion.return_value = None
        completion(messages=[])
    return litellm_completion.call_args.kwargs


def test_request_access_and_settings_reach_the_litellm_call():
    model_config = _model_config()

    apply_request_access(
        model_config,
        api_key="sk-request",
        extra_headers={"X-Gateway-Key": "resolved"},
        connection={"api_base": "http://gw/v1", "aws_region_name": "eu-west-1"},
        call_arguments={"temperature": 0.2},
    )

    arguments = _litellm_arguments(model_config)
    assert arguments["model"] == "openai/m"
    assert arguments["api_key"] == "sk-request"
    assert arguments["api_base"] == "http://gw/v1"
    assert arguments["aws_region_name"] == "eu-west-1"
    assert arguments["temperature"] == 0.2
    assert arguments["extra_headers"] == {"X-Gateway-Key": "resolved"}


def test_azure_calls_its_deployment_and_never_sends_deployment_id():
    model_config = _model_config(model_provider="azure", model="gpt-4o")

    apply_request_access(
        model_config,
        api_key="sk-azure",
        extra_headers={},
        connection={
            "api_base": "https://acme.openai.azure.com",
            "api_version": "2024-10-21",
            "deployment_id": "acme-gpt4o",
        },
        call_arguments={},
    )

    arguments = _litellm_arguments(model_config)
    assert arguments["model"] == "azure/acme-gpt4o"
    assert arguments["api_base"] == "https://acme.openai.azure.com"
    assert arguments["api_version"] == "2024-10-21"
    assert "deployment_id" not in arguments


def test_a_model_stored_with_its_provider_prefix_is_not_prefixed_twice():
    model_config = _model_config(model_provider="gemini", model="gemini/text-embedding-004")

    apply_request_access(
        model_config, api_key="k", extra_headers={}, connection={}, call_arguments={}
    )

    assert _litellm_arguments(model_config)["model"] == "gemini/text-embedding-004"


def test_empty_connection_values_and_headers_are_not_sent_and_no_placeholder_remains():
    model_config = _model_config()

    apply_request_access(
        model_config,
        api_key=None,
        extra_headers={},
        connection={"api_base": ""},
        call_arguments={"temperature": 0.2},
    )

    assert model_config.call_args == {"temperature": 0.2}
    # No placeholder is left to be sent.
    assert model_config.api_base is None
    assert model_config.api_key is None


async def test_graphrag_llm_forwards_call_args_to_litellm_embedding():
    """Pins the graphrag_llm contract apply_request_access relies on: call_args
    reach the litellm call unchanged."""
    model_config = _model_config()
    apply_request_access(
        model_config,
        api_key="k",
        extra_headers={"X-Gateway-Key": "resolved"},
        connection={"vertex_project": "acme"},
        call_arguments={},
    )
    _, embed_async = lite_llm_embedding._create_base_embeddings(
        model_config=model_config,
        drop_unsupported_params=True,
        azure_cognitive_services_audience="",
    )
    litellm_response = {
        "data": [{"embedding": [0.1], "index": 0, "object": "embedding"}],
        "model": "m",
        "object": "list",
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }
    mock = AsyncMock(
        return_value=type("Resp", (), {"model_dump": lambda self: litellm_response})()
    )

    with patch.object(lite_llm_embedding.litellm, "aembedding", mock):
        response = await embed_async(input=["hi"])

    assert response.first_embedding == [0.1]
    assert mock.await_args.kwargs["extra_headers"] == {"X-Gateway-Key": "resolved"}
    assert mock.await_args.kwargs["vertex_project"] == "acme"


@pytest.mark.parametrize(
    ("provider", "parameters", "expected"),
    [
        # Unset settings are left out, and stop sequences are never sent.
        (
            "openai",
            {"temperature": 0.5, "seed": None, "stop": ["Observation:"], "max_tokens": 2048},
            {"temperature": 0.5, "max_tokens": 2048},
        ),
        # Anthropic rejects sampling settings while thinking is on.
        (
            "anthropic",
            {"temperature": 0.5, "top_p": 0.9, "reasoning_effort": "high"},
            {"reasoning_effort": "high"},
        ),
    ],
    ids=["unset-and-stop", "anthropic-thinking"],
)
def test_completion_call_arguments_are_the_request_s_settings_graphrag_may_send(
    provider, parameters, expected
):
    model_config = _model_config(model_provider=provider)

    assert completion_call_arguments(model_config, parameters) == expected


def test_completion_call_arguments_leave_out_sampling_settings_the_model_refuses():
    model_config = _model_config(model_provider="bedrock", model="us.anthropic.claude-sonnet-5-5")

    assert completion_call_arguments(
        model_config, {"temperature": 0.5, "top_p": 0.9, "max_tokens": 2048}
    ) == {"max_tokens": 2048}
