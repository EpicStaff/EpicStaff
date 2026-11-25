from dataclasses import replace
from typing import Literal

import pytest
from ai_models.domain.builder import CatalogBuilder
from ai_models.domain.discovery import (
    EmbeddingParameterDiscoveryStrategy,
    LLMParameterDiscoveryStrategy,
    TranscriptionParameterDiscoveryStrategy,
)
from ai_models.domain.specs import ModelKind
from ai_models.domain.value_types import ValueTypeRegistry

from tests.ai_models_tests.factories import (
    FakeLiteLLMAdapter,
    make_model,
    make_parameter,
    make_registry,
)


def _build(adapter: FakeLiteLLMAdapter, registry=None):
    registry = registry or make_registry(recommended_models={"openai": frozenset({"gpt-4o"})})
    strategies = [
        strategy_class(adapter, registry)
        for strategy_class in (
            LLMParameterDiscoveryStrategy,
            EmbeddingParameterDiscoveryStrategy,
            TranscriptionParameterDiscoveryStrategy,
        )
    ]
    return CatalogBuilder(adapter, registry, strategies, ValueTypeRegistry()).build()


@pytest.fixture
def adapter() -> FakeLiteLLMAdapter:
    return FakeLiteLLMAdapter(
        models=[
            make_model(name="gpt-4o", limits={"max_output_tokens": 16384}),
            make_model(name="gpt-4o-mini"),
            make_model(name="aihubmix/agnes-2.5-flash", provider="aihubmix"),
            make_model(name="text-embedding-3-small", kind=ModelKind.EMBEDDING),
        ],
        llm={
            "gpt-4o": ("temperature", "verbosity", "tools"),
            "gpt-4o-mini": ("temperature",),
            "aihubmix/agnes-2.5-flash": ("temperature", "seed"),
        },
        embedding={"openai": ("dimensions",)},
        annotations={"verbosity": Literal["low", "medium", "high"] | None, "seed": int | None},
    )


def test_unknown_setting_becomes_draft(adapter):
    catalog = _build(adapter)

    verbosity = catalog.parameters["verbosity"]
    assert verbosity.draft is True
    assert verbosity.value_type == "choice"
    assert verbosity.minimum is None and verbosity.maximum is None and verbosity.options == ()
    assert verbosity.default is None
    assert catalog.parameters["temperature"].draft is False


def test_draft_without_a_litellm_type_hint_is_json(adapter):
    adapter.llm = {"gpt-4o": ("thinking",)}

    assert _build(adapter).parameters["thinking"].value_type == "json"


def test_models_carry_their_discovered_settings(adapter):
    catalog = _build(adapter)

    gpt_4o = catalog.models[ModelKind.LLM]["openai"]["gpt-4o"]
    assert gpt_4o.parameter_names == ("temperature", "verbosity")
    assert gpt_4o.limits == {"max_output_tokens": 16384}
    assert catalog.models[ModelKind.EMBEDDING]["openai"]["text-embedding-3-small"].parameter_names == (
        "dimensions",
    )


def test_recommended_flag_comes_from_the_registry(adapter):
    models = _build(adapter).models[ModelKind.LLM]["openai"]

    assert models["gpt-4o"].recommended is True
    assert models["gpt-4o-mini"].recommended is False


def test_models_of_unlisted_providers_are_kept_without_a_provider_spec(adapter):
    catalog = _build(adapter)

    assert "aihubmix/agnes-2.5-flash" in catalog.models[ModelKind.LLM]["aihubmix"]
    assert set(catalog.providers) == {"openai"}


def test_settings_offered_for_custom_models_are_kept_and_unused_ones_left_out():
    registry = make_registry(
        parameters={"temperature": make_parameter("temperature"), "seed": make_parameter("seed")}
    )
    catalog = _build(FakeLiteLLMAdapter(), registry)

    assert catalog.parameters == {"temperature": registry.parameter("temperature")}
    assert catalog.models == {}


def test_each_setting_stored_once(adapter):
    text = _build(adapter).to_json()

    assert text.count('"temperature": {') == 1


def test_build_is_deterministic(adapter):
    first = _build(adapter).to_json()
    adapter.models = list(reversed(adapter.models))

    assert _build(adapter).to_json() == first


def test_changes_lists_added_models_and_drafts(adapter):
    previous = _build(FakeLiteLLMAdapter(models=adapter.models[:1], llm={"gpt-4o": ("temperature",)}))
    current = _build(adapter)

    assert CatalogBuilder.changes(previous, current) == [
        "models added: 3",
        "models removed: 0",
        "settings appeared: dimensions, seed, verbosity",
        "settings disappeared: none",
        "drafts waiting: dimensions, seed, verbosity",
    ]


def test_changes_lists_removed_models_and_settings(adapter):
    previous = _build(adapter)
    current = replace(
        previous,
        parameters={"temperature": previous.parameters["temperature"]},
        models={ModelKind.LLM: {"openai": {"gpt-4o": previous.models[ModelKind.LLM]["openai"]["gpt-4o"]}}},
    )

    assert CatalogBuilder.changes(previous, current) == [
        "models added: 0",
        "models removed: 3",
        "settings appeared: none",
        "settings disappeared: dimensions, seed, verbosity",
        "drafts waiting: none",
    ]


def test_changes_without_a_previous_catalog_counts_every_model_as_added(adapter):
    assert CatalogBuilder.changes(None, _build(adapter))[0] == "models added: 4"
