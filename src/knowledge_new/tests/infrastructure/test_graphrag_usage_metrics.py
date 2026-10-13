import types

from graphrag_llm.completion import create_completion
from graphrag_llm.completion.completion_factory import completion_factory
from graphrag_llm.config import ModelConfig
from graphrag_llm.embedding import create_embedding
from graphrag_llm.embedding.embedding_factory import embedding_factory
from infrastructure.graphrag.usage_metrics import track_usage


def _config() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        embedding_models={
            "default_embedding_model": ModelConfig(
                model_provider="openai",
                model="text-embedding-3-small",
                api_key="usage-metrics-test",
                call_args={"mock_response": [0.1, 0.2]},
            )
        },
        completion_models={
            "default_completion_model": ModelConfig(
                model_provider="openai",
                model="gpt-4o-mini",
                api_key="usage-metrics-test",
                call_args={"mock_response": "an answer"},
            )
        },
    )


async def _run(completions: int, embeddings: int):
    config = _config()
    with track_usage(config) as usage:
        completion = create_completion(config.completion_models["default_completion_model"])
        embedding = create_embedding(config.embedding_models["default_embedding_model"])
        for _ in range(completions):
            await completion.completion_async(messages="say something")
        for _ in range(embeddings):
            await embedding.embedding_async(input=["some text"])
    return usage


async def test_sequential_runs_with_identical_config_keep_their_own_tally():
    first = await _run(completions=1, embeddings=1)
    second = await _run(completions=3, embeddings=0)

    assert first.llm_input_tokens > 0
    assert first.embedding_tokens > 0
    assert second.llm_input_tokens == 3 * first.llm_input_tokens
    assert second.embedding_tokens == 0


async def test_runs_do_not_grow_the_model_cache():
    await _run(completions=1, embeddings=1)
    cached = (
        len(completion_factory._initialized_services),
        len(embedding_factory._initialized_services),
    )

    await _run(completions=1, embeddings=1)
    await _run(completions=1, embeddings=1)

    assert (
        len(completion_factory._initialized_services),
        len(embedding_factory._initialized_services),
    ) == cached


async def test_calls_outside_a_tracked_block_are_not_counted():
    config = _config()
    with track_usage(config) as usage:
        completion = create_completion(config.completion_models["default_completion_model"])

    await completion.completion_async(messages="say something")

    assert usage.is_empty
