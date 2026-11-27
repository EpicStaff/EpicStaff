from dataclasses import replace

import pytest
from ai_models.domain.checks import (
    CatalogChecker,
    CatalogCheckFinding,
    CatalogUpToDateRule,
    ChoiceOptionsRequiredRule,
    ConnectionFieldsRequiredRule,
    NoDraftParametersRule,
    NumberRangeRequiredRule,
    UnclassifiedThinkingModelRule,
    UnusedRegistryEntryRule,
)
from ai_models.domain.specs import DefaultThinkingSpec, ModelKind

from tests.ai_models_tests.factories import (
    FakeLiteLLMAdapter,
    make_catalog,
    make_model,
    make_parameter,
    make_provider,
    make_registry,
)


def _with_parameter(catalog, parameter):
    return replace(catalog, parameters={**catalog.parameters, parameter.name: parameter})


def _with_provider(catalog, provider):
    return replace(catalog, providers={**catalog.providers, provider.name: provider})


def _draft_catalog():
    return _with_parameter(make_catalog(), make_parameter("verbosity", value_type="choice", draft=True))


def _number_without_maximum_catalog():
    return _with_parameter(make_catalog(), make_parameter("top_k", value_type="integer", minimum=1))


def _number_without_minimum_catalog():
    return _with_parameter(make_catalog(), make_parameter("top_k", value_type="integer", maximum=100))


def _choice_without_options_catalog():
    return _with_parameter(make_catalog(), make_parameter("verbosity", value_type="choice", control="select"))


def _provider_without_connection_fields_catalog():
    return _with_provider(make_catalog(), make_provider(name="watsonx", label="watsonx", connection_fields=()))


@pytest.mark.parametrize(
    ("rule", "bad_catalog", "named"),
    [
        (NoDraftParametersRule(), _draft_catalog(), "verbosity"),
        (NumberRangeRequiredRule(), _number_without_maximum_catalog(), "top_k"),
        (NumberRangeRequiredRule(), _number_without_minimum_catalog(), "top_k"),
        (ChoiceOptionsRequiredRule(), _choice_without_options_catalog(), "verbosity"),
        (ConnectionFieldsRequiredRule(), _provider_without_connection_fields_catalog(), "watsonx"),
    ],
)
def test_rule_reports_one_error_naming_the_culprit(rule, bad_catalog, named):
    findings = rule.check(bad_catalog, bad_catalog, make_registry())

    assert len(findings) == 1
    assert findings[0].is_error is True
    assert findings[0].rule == type(rule).__name__
    assert named in findings[0].message


@pytest.mark.parametrize(
    "rule",
    [
        NoDraftParametersRule(),
        NumberRangeRequiredRule(),
        ChoiceOptionsRequiredRule(),
        CatalogUpToDateRule(),
        ConnectionFieldsRequiredRule(),
        UnusedRegistryEntryRule(),
        UnclassifiedThinkingModelRule(FakeLiteLLMAdapter()),
    ],
)
def test_rule_passes_a_complete_current_catalog(rule):
    catalog = make_catalog()

    assert rule.check(catalog, catalog, make_registry()) == []


def test_number_range_may_come_from_a_model_limit():
    catalog = _with_parameter(
        make_catalog(),
        make_parameter("max_tokens", value_type="integer", minimum=1, limit_from="max_output_tokens"),
    )

    assert NumberRangeRequiredRule().check(catalog, catalog, make_registry()) == []


def test_drafts_are_left_to_the_draft_rule():
    draft = make_parameter("top_k", value_type="integer", draft=True)
    catalog = _with_parameter(make_catalog(), draft)

    assert NumberRangeRequiredRule().check(catalog, catalog, make_registry()) == []


def test_provider_the_runtime_cannot_run_needs_no_connection_fields():
    catalog = _with_provider(make_catalog(), make_provider(name="voyage", kinds=(), connection_fields=()))

    assert ConnectionFieldsRequiredRule().check(catalog, catalog, make_registry()) == []


def test_stale_committed_catalog_is_one_error():
    committed = make_catalog()
    fresh = replace(committed, litellm_version="1.200.0")

    findings = CatalogUpToDateRule().check(committed, fresh, make_registry())

    assert len(findings) == 1
    assert findings[0].is_error is True
    assert "1.200.0" in findings[0].message


def test_registry_provider_no_model_uses_is_a_warning():
    registry = make_registry(providers={"openai": make_provider(), "voyage": make_provider(name="voyage")})
    catalog = make_catalog()

    findings = UnusedRegistryEntryRule().check(catalog, catalog, registry)

    assert findings == [
        CatalogCheckFinding(
            rule="UnusedRegistryEntryRule",
            message="voyage: in parameter_registry.yaml, but LiteLLM has no model of it.",
            is_error=False,
        )
    ]


def test_checker_collects_the_findings_of_every_rule():
    committed = _draft_catalog()
    fresh = replace(committed, litellm_version="1.200.0")
    checker = CatalogChecker([NoDraftParametersRule(), CatalogUpToDateRule(), ChoiceOptionsRequiredRule()])

    findings = checker.run(committed, fresh, make_registry())

    assert [finding.rule for finding in findings] == ["NoDraftParametersRule", "CatalogUpToDateRule"]


def test_unused_rule_counts_models_of_every_kind():
    registry = make_registry(providers={"openai": make_provider(), "vertex_ai": make_provider(name="vertex_ai")})
    catalog = make_catalog()
    vertex_embeds_only = replace(
        catalog,
        models={
            ModelKind.LLM: catalog.models[ModelKind.LLM],
            ModelKind.EMBEDDING: {"vertex_ai": catalog.models[ModelKind.EMBEDDING]["openai"]},
        },
    )

    assert UnusedRegistryEntryRule().check(vertex_embeds_only, vertex_embeds_only, registry) == []


def _with_llm_models(catalog, provider, *models):
    llm_models = {**catalog.models[ModelKind.LLM], provider: {model.name: model for model in models}}
    return replace(catalog, models={**catalog.models, ModelKind.LLM: llm_models})


_THINKING_MODELS = ("claude-new", "us.anthropic.claude-new-fast", "claude-asks")
_ADAPTIVE = FakeLiteLLMAdapter(adaptive_thinking=frozenset({*_THINKING_MODELS, "other-thinker"}))


def test_adaptive_thinking_model_no_entry_classifies_is_an_error_naming_it():
    catalog = _with_llm_models(make_catalog(), "openai", *(make_model(name=name) for name in _THINKING_MODELS))
    registry = make_registry(default_thinking={"claude-asks": None})

    findings = UnclassifiedThinkingModelRule(_ADAPTIVE).check(catalog, catalog, registry)

    assert [finding.is_error for finding in findings] == [True, True]
    assert [finding.message.split(":")[0] for finding in findings] == ["claude-new", "us.anthropic.claude-new-fast"]


def test_classified_adaptive_thinking_models_pass():
    catalog = _with_llm_models(make_catalog(), "openai", *(make_model(name=name) for name in _THINKING_MODELS))
    registry = make_registry(
        default_thinking={"claude-new": DefaultThinkingSpec("high", "disabled"), "claude-asks": None}
    )

    assert UnclassifiedThinkingModelRule(_ADAPTIVE).check(catalog, catalog, registry) == []


def test_adaptive_thinking_model_of_a_provider_no_config_can_use_is_not_checked():
    catalog = _with_llm_models(make_catalog(), "tencent", make_model(name="other-thinker", provider="tencent"))

    assert UnclassifiedThinkingModelRule(_ADAPTIVE).check(catalog, catalog, make_registry()) == []


def test_default_thinking_entry_no_model_matches_is_a_warning():
    catalog = _with_llm_models(make_catalog(), "openai", make_model(name="vertex_ai/claude-new@default"))
    registry = make_registry(default_thinking={"claude-new": None, "claude-gone": None})

    findings = UnusedRegistryEntryRule().check(catalog, catalog, registry)

    assert findings == [
        CatalogCheckFinding(
            rule="UnusedRegistryEntryRule",
            message="claude-gone: in parameter_registry.yaml, but LiteLLM has no model of it.",
            is_error=False,
        )
    ]
