import pytest
from ai_models.domain.discovery import (
    EmbeddingParameterDiscoveryStrategy,
    LLMParameterDiscoveryStrategy,
    TranscriptionParameterDiscoveryStrategy,
)
from ai_models.domain.specs import ModelKind

from tests.ai_models_tests.factories import FakeLiteLLMAdapter, make_model, make_registry

STRATEGIES_DECLARED_PER_PROVIDER = [
    (EmbeddingParameterDiscoveryStrategy, ModelKind.EMBEDDING, "embedding"),
    (TranscriptionParameterDiscoveryStrategy, ModelKind.TRANSCRIPTION, "transcription"),
]


def test_llm_settings_come_from_litellm_sorted_without_hidden_names():
    adapter = FakeLiteLLMAdapter(llm={"gpt-4o": ("top_p", "tools", "temperature", "stream")})
    strategy = LLMParameterDiscoveryStrategy(adapter, make_registry())

    assert strategy.discover(make_model(name="gpt-4o")) == ("temperature", "top_p")


@pytest.mark.parametrize(("strategy_class", "kind", "adapter_field"), STRATEGIES_DECLARED_PER_PROVIDER)
def test_registry_list_wins_over_litellm(strategy_class, kind, adapter_field):
    adapter = FakeLiteLLMAdapter(**{adapter_field: {"openai": ("encoding_format", "user")}})
    registry = make_registry(kind_parameters={kind: {"openai": ("dimensions",)}})
    strategy = strategy_class(adapter, registry)

    assert strategy.discover(make_model(kind=kind)) == ("dimensions",)


@pytest.mark.parametrize(("strategy_class", "kind", "adapter_field"), STRATEGIES_DECLARED_PER_PROVIDER)
def test_empty_registry_list_means_no_settings(strategy_class, kind, adapter_field):
    adapter = FakeLiteLLMAdapter(**{adapter_field: {"openai": ("encoding_format",)}})
    strategy = strategy_class(adapter, make_registry(kind_parameters={kind: {"openai": ()}}))

    assert strategy.discover(make_model(kind=kind)) == ()


@pytest.mark.parametrize(("strategy_class", "kind", "adapter_field"), STRATEGIES_DECLARED_PER_PROVIDER)
def test_without_registry_list_litellm_answers_without_hidden_names(
    strategy_class, kind, adapter_field
):
    adapter = FakeLiteLLMAdapter(**{adapter_field: {"voyage": ("tools", "encoding_format", "dimensions")}})
    strategy = strategy_class(adapter, make_registry())

    assert strategy.discover(make_model(provider="voyage", kind=kind)) == (
        "dimensions",
        "encoding_format",
    )


@pytest.mark.parametrize(("strategy_class", "kind", "adapter_field"), STRATEGIES_DECLARED_PER_PROVIDER)
def test_provider_unknown_to_registry_and_litellm_has_no_settings(
    strategy_class, kind, adapter_field
):
    strategy = strategy_class(FakeLiteLLMAdapter(), make_registry())

    assert strategy.discover(make_model(provider="aihubmix", kind=kind)) == ()
