"""The adapter against the installed LiteLLM: these pin what we rely on LiteLLM's data for."""

import litellm
import pytest
from ai_models.domain.specs import ModelKind
from ai_models.litellm_adapter import CatalogSourceError, LiteLLMAdapter


@pytest.fixture(scope="module")
def adapter() -> LiteLLMAdapter:
    return LiteLLMAdapter()


@pytest.fixture(scope="module")
def entries(adapter) -> dict[ModelKind, dict[tuple[str, str], object]]:
    return {
        kind: {(model.provider, model.name): model for model in adapter.model_entries(kind)}
        for kind in ModelKind
    }


def test_chat_model_comes_with_its_limits(entries):
    gpt_4o = entries[ModelKind.LLM][("openai", "gpt-4o")]

    assert gpt_4o.kind == ModelKind.LLM
    assert gpt_4o.limits["max_output_tokens"] > 0
    assert gpt_4o.limits["max_input_tokens"] > 0
    assert gpt_4o.parameter_names == ()


@pytest.mark.parametrize(
    ("kind", "provider", "name"),
    [
        (ModelKind.EMBEDDING, "openai", "text-embedding-3-small"),
        (ModelKind.TRANSCRIPTION, "openai", "whisper-1"),
    ],
)
def test_each_kind_reads_its_own_litellm_mode(entries, kind, provider, name):
    assert (provider, name) in entries[kind]
    assert all((provider, name) not in entries[other] for other in ModelKind if other != kind)


@pytest.mark.parametrize(
    ("kind", "provider", "name"),
    [
        # Filed under "vertex_ai-anthropic_models".
        (ModelKind.LLM, "vertex_ai", "vertex_ai/claude-3-5-haiku"),
        # Filed under "cohere_chat".
        (ModelKind.LLM, "cohere", "command-a-03-2025"),
        # Filed under "bedrock_converse".
        (ModelKind.LLM, "bedrock", "us.writer.palmyra-x4-v1:0"),
        # Filed under "fireworks_ai-embedding-models".
        (ModelKind.EMBEDDING, "fireworks_ai", "fireworks_ai/nomic-ai/nomic-embed-text-v1.5"),
    ],
)
def test_provider_variants_become_the_provider_they_are_called_through(entries, kind, provider, name):
    assert (provider, name) in entries[kind]


def test_no_model_keeps_a_variant_provider_name(entries):
    providers = {provider for by_kind in entries.values() for provider, _ in by_kind}

    assert not [provider for provider in providers if provider.startswith("vertex_ai-")]
    assert not providers & {"cohere_chat", "bedrock_converse", "fireworks_ai-embedding-models"}


@pytest.mark.parametrize(
    ("provider", "name"),
    [("openai", "gpt-4o"), ("anthropic", "claude-sonnet-4-5"), ("gemini", "gemini/gemini-2.5-flash")],
)
def test_names_stay_in_the_form_model_rows_store(entries, provider, name):
    assert (provider, name) in entries[ModelKind.LLM]


@pytest.mark.parametrize(
    ("provider", "kept", "dropped"),
    [
        ("vertex_ai", "vertex_ai/gemini-3.5-flash", "gemini-3.5-flash"),
        ("deepseek", "deepseek/deepseek-chat", "deepseek-chat"),
    ],
)
def test_a_model_listed_twice_is_kept_once_under_its_prefixed_name(entries, provider, kept, dropped):
    assert (provider, kept) in entries[ModelKind.LLM]
    assert (provider, dropped) not in entries[ModelKind.LLM]


def test_reasoning_levels_come_from_litellm(entries):
    glm = entries[ModelKind.LLM][("friendliai", "friendliai/zai-org/GLM-5.3")]

    assert glm.options["reasoning_effort"] == ("low", "high", "max")
    assert "reasoning_effort" not in entries[ModelKind.LLM][("openai", "gpt-4o")].options


def test_llm_parameters_come_from_litellm(adapter, entries):
    names = adapter.llm_parameters(entries[ModelKind.LLM][("openai", "gpt-4o")])

    assert {"temperature", "top_p", "max_tokens", "tools"} <= set(names)


def test_embedding_parameters_without_a_litellm_config_class_are_none(adapter):
    # LiteLLM's generic call would answer the chat settings here; the adapter must not.
    assert adapter.embedding_parameters("openai") is None
    assert adapter.embedding_parameters("aihubmix") is None
    assert set(adapter.embedding_parameters("cohere")) == {"encoding_format", "dimensions"}


def test_transcription_parameters(adapter):
    assert "language" in adapter.transcription_parameters("openai")
    assert adapter.transcription_parameters("aihubmix") is None


def test_credential_names_do_not_depend_on_the_environment(adapter, entries, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "set-on-this-machine")

    assert adapter.credential_names(entries[ModelKind.LLM][("openai", "gpt-4o")]) == ("OPENAI_API_KEY",)


def test_completion_annotations_come_from_the_typed_signature(adapter):
    annotations = adapter.completion_annotations()

    assert annotations["temperature"] == (float | None)
    assert annotations["logprobs"] == (bool | None)


def test_version_is_the_installed_release(adapter):
    assert adapter.version().count(".") == 2


def test_litellm_failure_becomes_catalog_source_error(adapter, entries, monkeypatch):
    def broken(**kwargs):
        raise KeyError("moved in a LiteLLM release")

    monkeypatch.setattr(litellm, "get_supported_openai_params", broken)

    with pytest.raises(CatalogSourceError, match="moved in a LiteLLM release"):
        adapter.llm_parameters(entries[ModelKind.LLM][("openai", "gpt-4o")])
