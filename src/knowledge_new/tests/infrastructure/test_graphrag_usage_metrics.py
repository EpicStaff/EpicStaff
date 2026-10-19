import types

import litellm
import pytest
from graphrag_llm.completion import create_completion
from graphrag_llm.completion.completion_factory import completion_factory
from graphrag_llm.config import ModelConfig
from graphrag_llm.embedding import create_embedding
from graphrag_llm.embedding.embedding_factory import embedding_factory
from domain.usage import UsageTally
from infrastructure.graphrag.usage_metrics import StreamUsageCompletion, _tally_stream_usage, track_usage


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


def _streaming_config() -> types.SimpleNamespace:
    config = _config()
    config.completion_models["default_completion_model"].call_args = {"mock_response": "an answer to stream"}
    return config


def _completion(config):
    return create_completion(config.completion_models["default_completion_model"])


async def _stream(completion) -> list:
    stream = await completion.completion_async(messages="say something", stream=True)
    return [chunk async for chunk in stream]


async def test_streamed_completion_is_counted():
    config = _streaming_config()
    with track_usage(config) as usage:
        chunks = await _stream(_completion(config))

    assert chunks
    assert usage.llm_input_tokens > 0
    assert usage.llm_output_tokens > 0


async def test_stream_chunks_are_passed_through_unchanged():
    config = _streaming_config()
    with track_usage(config):
        completion = _completion(config)
        tracked = await _stream(completion)
    text = "".join(chunk.choices[0].delta.content or "" for chunk in tracked if chunk.choices)

    assert text == "an answer to stream"


async def test_include_usage_is_requested_for_streams():
    config = _streaming_config()
    with track_usage(config):
        completion = _completion(config)
        seen: dict = {}
        original = completion._completion_async

        async def spy(**kwargs):
            seen.update(kwargs)
            return await original(**kwargs)

        completion._completion_async = spy
        await _stream(completion)

    assert seen["stream_options"] == {"include_usage": True}


async def test_usage_repeated_on_several_chunks_is_not_double_counted():
    async def chunks():
        for prompt, completion_tokens in [(10, 1), (10, 5), (10, 5)]:
            yield types.SimpleNamespace(
                usage=types.SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion_tokens),
                choices=[object()],
            )

    tally = UsageTally()
    passed = [chunk async for chunk in _tally_stream_usage(chunks(), tally)]

    assert len(passed) == 3
    assert (tally.llm_input_tokens, tally.llm_output_tokens) == (10, 5)


async def test_stream_without_usage_chunk_counts_nothing():
    async def chunks():
        yield types.SimpleNamespace(usage=None, choices=[object()])

    tally = UsageTally()
    _ = [chunk async for chunk in _tally_stream_usage(chunks(), tally)]

    assert tally.is_empty


async def test_stream_outside_a_tracked_block_is_not_counted():
    config = _streaming_config()
    with track_usage(config) as usage:
        completion = _completion(config)

    chunks = await _stream(completion)

    assert chunks
    assert usage.is_empty


async def test_basic_search_records_the_streamed_answer_tokens():
    from graphrag.query.structured_search.basic_search.search import BasicSearch

    config = _streaming_config()
    context_result = types.SimpleNamespace(context_chunks="context", context_records={})
    context_builder = types.SimpleNamespace(build_context=lambda **_: context_result)
    with track_usage(config) as usage:
        model = _completion(config)
        search = BasicSearch(model=model, context_builder=context_builder, tokenizer=model.tokenizer)
        answer = "".join([text async for text in search.stream_search("a question")])

    assert answer == "an answer to stream"
    assert usage.llm_input_tokens > 0
    assert usage.llm_output_tokens > 0


def _delta_chunk(text):
    return types.SimpleNamespace(usage=None, choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=text))])


def _usage_chunk(prompt, completion_tokens):
    return types.SimpleNamespace(
        usage=types.SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion_tokens), choices=[]
    )


async def test_usage_only_chunk_is_tallied_and_not_yielded():
    async def chunks():
        yield _delta_chunk("hi")
        yield _usage_chunk(7, 3)

    tally = UsageTally()
    passed = [chunk async for chunk in _tally_stream_usage(chunks(), tally)]

    assert len(passed) == 1
    assert (tally.llm_input_tokens, tally.llm_output_tokens) == (7, 3)


async def test_graphrag_style_consumer_does_not_raise_on_usage_chunk():
    async def chunks():
        yield _delta_chunk("a")
        yield _delta_chunk("b")
        yield _usage_chunk(1, 2)

    text = ""
    async for chunk in _tally_stream_usage(chunks(), UsageTally()):
        text += chunk.choices[0].delta.content

    assert text == "ab"


async def test_closing_the_wrapper_closes_the_inner_stream_and_records_usage():
    closed = []

    class Inner:
        def __aiter__(self):
            return self._generate()

        async def _generate(self):
            first = _delta_chunk("first")
            first.usage = types.SimpleNamespace(prompt_tokens=4, completion_tokens=2)
            yield first
            yield _delta_chunk("never read")

        async def aclose(self):
            closed.append(True)

    tally = UsageTally()
    wrapped = _tally_stream_usage(Inner(), tally)
    await wrapped.__anext__()
    await wrapped.aclose()

    assert closed == [True]
    assert (tally.llm_input_tokens, tally.llm_output_tokens) == (4, 2)


def _bad_request():
    return litellm.BadRequestError(message="stream_options not supported", model="m", llm_provider="openai")


async def _one_chunk_stream():
    yield _delta_chunk("ok")


def _patch_parent(monkeypatch, behaviour):
    calls = []

    async def fake(self, /, **kwargs):
        calls.append(kwargs)
        return await behaviour(kwargs)

    monkeypatch.setattr("infrastructure.graphrag.usage_metrics.LiteLLMCompletion.completion_async", fake)
    return calls


def _bare_completion():
    return StreamUsageCompletion.__new__(StreamUsageCompletion)


async def test_bad_request_retries_once_without_our_stream_options(monkeypatch):
    async def behaviour(kwargs):
        if "stream_options" in kwargs:
            raise _bad_request()
        return _one_chunk_stream()

    calls = _patch_parent(monkeypatch, behaviour)
    with track_usage(_streaming_config()) as usage:
        stream = await _bare_completion().completion_async(messages="x", stream=True)
        chunks = [chunk async for chunk in stream]

    assert len(calls) == 2
    assert "stream_options" in calls[0]
    assert "stream_options" not in calls[1]
    assert len(chunks) == 1
    assert usage.is_empty


async def test_no_retry_when_caller_supplied_stream_options(monkeypatch):
    async def behaviour(kwargs):
        raise _bad_request()

    calls = _patch_parent(monkeypatch, behaviour)
    with track_usage(_streaming_config()):
        with pytest.raises(litellm.BadRequestError):
            await _bare_completion().completion_async(messages="x", stream=True, stream_options={"include_usage": False})

    assert len(calls) == 1


async def test_no_retry_on_other_errors(monkeypatch):
    async def behaviour(kwargs):
        raise RuntimeError("boom")

    calls = _patch_parent(monkeypatch, behaviour)
    with track_usage(_streaming_config()):
        with pytest.raises(RuntimeError):
            await _bare_completion().completion_async(messages="x", stream=True)

    assert len(calls) == 1


async def test_non_streamed_completion_is_counted_exactly_once():
    config = _config()
    with track_usage(config) as once:
        await _completion(config).completion_async(messages="say something")
    with track_usage(config) as twice:
        completion = _completion(config)
        await completion.completion_async(messages="say something")
        await completion.completion_async(messages="say something")

    assert once.llm_input_tokens > 0
    assert twice.llm_input_tokens == 2 * once.llm_input_tokens
    assert twice.llm_output_tokens == 2 * once.llm_output_tokens
