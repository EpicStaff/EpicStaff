from unittest.mock import AsyncMock, patch

from graphrag_llm.config import ModelConfig
from graphrag_llm.embedding import lite_llm_embedding
from infrastructure.graphrag.model_headers import set_extra_headers


def _model_config(**overrides) -> ModelConfig:
    return ModelConfig(model_provider="openai", model="m", api_key="sk-test", **overrides)


def test_headers_are_added_to_call_args_keeping_existing_ones():
    model_config = _model_config(call_args={"temperature": 0.2})

    set_extra_headers(model_config, {"X-Gateway-Key": "resolved"})

    assert model_config.call_args == {
        "temperature": 0.2,
        "extra_headers": {"X-Gateway-Key": "resolved"},
    }


def test_empty_headers_leave_call_args_untouched():
    model_config = _model_config(call_args={"temperature": 0.2})

    set_extra_headers(model_config, {})

    assert model_config.call_args == {"temperature": 0.2}


async def test_graphrag_llm_forwards_call_args_headers_to_litellm():
    """Pins the graphrag_llm contract set_extra_headers relies on: call_args
    reach the litellm call unchanged."""
    model_config = _model_config()
    set_extra_headers(model_config, {"X-Gateway-Key": "resolved"})
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
