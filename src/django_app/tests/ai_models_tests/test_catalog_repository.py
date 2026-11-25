from dataclasses import replace

import pytest
from ai_models.domain.catalog import Catalog
from ai_models.domain.specs import ModelKind
from ai_models.repository import CatalogRepository

from tests.ai_models_tests.factories import make_provider, make_runtime_catalog


@pytest.fixture
def repository():
    return CatalogRepository(make_runtime_catalog())


def _names(items):
    return [item.name for item in items]


def test_providers_lists_runnable_providers_recommended_first_then_by_label(repository):
    # Left out: watsonx (no model, no custom models), legacy_ai (only a deprecated
    # model), mystery (no ProviderSpec) and voyage (does not run llm).
    assert _names(repository.providers(ModelKind.LLM)) == [
        "anthropic",
        "openai",
        "bedrock",
        "ollama",
    ]


def test_providers_are_ordered_by_label_ignoring_case():
    providers = {
        name: make_provider(name=name, label=label, recommended=False)
        for name, label in [("sagemaker", "AWS SageMaker"), ("anyscale", "Anyscale"), ("v0", "v0")]
    }
    catalog = Catalog(litellm_version="1.108.1", parameters={}, providers=providers, models={})

    assert _names(CatalogRepository(catalog).providers(ModelKind.LLM)) == ["anyscale", "sagemaker", "v0"]


def test_providers_of_a_kind_skip_providers_that_no_longer_run_it(repository):
    # voyage and bedrock have embedding models, but their specs do not list embedding.
    assert _names(repository.providers(ModelKind.EMBEDDING)) == ["openai"]


def test_providers_of_a_kind_nobody_runs_is_empty(repository):
    assert repository.providers(ModelKind.TRANSCRIPTION) == []


def test_models_are_recommended_first_then_by_name_without_deprecated(repository):
    assert _names(repository.models(ModelKind.LLM, "openai")) == ["gpt-4o", "gpt-4o-mini", "gpt-7"]


def test_models_include_deprecated_on_request(repository):
    names = _names(repository.models(ModelKind.LLM, "openai", include_deprecated=True))

    assert names == ["gpt-4o", "gpt-3.5-turbo-0301", "gpt-4o-mini", "gpt-7"]


@pytest.mark.parametrize(("search", "expected"), [("MINI", ["gpt-4o-mini"]), ("4O", ["gpt-4o", "gpt-4o-mini"]), ("claude", [])])
def test_models_search_is_case_insensitive(repository, search, expected):
    assert _names(repository.models(ModelKind.LLM, "openai", search=search)) == expected


@pytest.mark.parametrize("provider", ["mystery", "nobody"])
def test_provider_without_spec_has_no_models(repository, provider):
    assert repository.models(ModelKind.LLM, provider) == []
    assert repository.model(ModelKind.LLM, provider, "mystery-1") is None


def test_model_finds_a_deprecated_model(repository):
    model = repository.model(ModelKind.LLM, "openai", "gpt-3.5-turbo-0301")

    assert model is not None and model.name == "gpt-3.5-turbo-0301"


def test_model_is_looked_up_per_kind(repository):
    assert repository.model(ModelKind.EMBEDDING, "openai", "gpt-4o") is None


def test_parameter_applies_provider_overrides(repository):
    assert repository.parameter("temperature", "anthropic").maximum == 1
    assert repository.parameter("temperature", "openai").maximum == 2


@pytest.mark.parametrize(
    ("kind", "provider", "model_name", "expected"),
    [
        (ModelKind.LLM, "openai", "gpt-4o-mini", ("max_tokens", "temperature")),
        # A custom model gets the provider's common list.
        (ModelKind.LLM, "openai", "my-fine-tune", ("temperature", "max_tokens", "seed")),
        # The provider no longer runs embedding: the common list, not the model's own.
        (ModelKind.EMBEDDING, "bedrock", "amazon.titan-embed", ("dimensions",)),
        (ModelKind.EMBEDDING, "voyage", "voyage-3", ()),
        (ModelKind.LLM, "nobody", "gpt-4o", ()),
        (ModelKind.LLM, "mystery", "mystery-1", ()),
    ],
)
def test_parameter_names(repository, kind, provider, model_name, expected):
    assert repository.parameter_names(kind, provider, model_name) == expected


def test_default_loads_the_committed_catalog_once():
    repository = CatalogRepository.default()

    assert repository is CatalogRepository.default()
    assert repository.model(ModelKind.LLM, "openai", "gpt-4o") is not None
    assert "openai" in _names(repository.providers(ModelKind.LLM))


@pytest.fixture
def aliased_repository():
    catalog = make_runtime_catalog()
    providers = {
        **catalog.providers,
        "anthropic": replace(catalog.providers["anthropic"], aliases=("anthropic_ai",)),
    }
    return CatalogRepository(replace(catalog, providers=providers))


def test_every_lookup_by_provider_takes_an_alias(aliased_repository):
    assert aliased_repository.provider("anthropic_ai").name == "anthropic"
    assert _names(aliased_repository.models(ModelKind.LLM, "anthropic_ai")) == ["claude-sonnet"]
    assert aliased_repository.model(ModelKind.LLM, "anthropic_ai", "claude-sonnet").provider == "anthropic"
    assert aliased_repository.parameter("temperature", "anthropic_ai").maximum == 1
    assert aliased_repository.parameter_names(ModelKind.LLM, "anthropic_ai", "claude-sonnet") == (
        "max_tokens",
        "temperature",
        "top_p",
    )
    # A custom model of the aliased provider gets the provider's common list.
    assert aliased_repository.parameter_names(ModelKind.LLM, "anthropic_ai", "claude-custom") == (
        "temperature",
        "top_p",
        "max_tokens",
    )


def test_committed_catalog_resolves_database_provider_names():
    repository = CatalogRepository.default()

    assert repository.provider("google_ai").name == "gemini"
    assert repository.model(ModelKind.LLM, "google_ai", "gemini/gemini-2.5-flash") is not None
    assert repository.provider("together-ai").name == "together_ai"


@pytest.mark.parametrize(
    ("provider", "stored_name", "expected"),
    [
        # A seed row stored `<provider>/<bare key>` where the catalog key is bare.
        ("anthropic", "anthropic/claude-sonnet", "claude-sonnet"),
        ("anthropic_ai", "anthropic/claude-sonnet", "claude-sonnet"),
        ("openai", "openai/gpt-4o", "gpt-4o"),
        ("anthropic", " claude-sonnet ", "claude-sonnet"),
    ],
)
def test_model_matches_a_stored_name_the_way_litellm_looks_it_up(
    aliased_repository, provider, stored_name, expected
):
    model = aliased_repository.model(ModelKind.LLM, provider, stored_name)

    assert model is not None and model.name == expected


def test_model_does_not_match_another_providers_prefix(repository):
    # `openai/gpt-4o` on an Anthropic row is an Anthropic model id, not OpenAI's gpt-4o.
    assert repository.model(ModelKind.LLM, "anthropic", "openai/gpt-4o") is None


@pytest.mark.parametrize(
    ("provider", "stored_name", "expected"),
    [
        # The reverse: the catalog key is prefixed, the stored name is bare.
        ("google_ai", "gemini-2.5-flash", "gemini/gemini-2.5-flash"),
        ("gemini", "gemini-2.5-flash", "gemini/gemini-2.5-flash"),
        ("anthropic", "anthropic/claude-haiku-4-5", "claude-haiku-4-5"),
        ("vertex_ai", "vertex_ai/gemini-2.5-flash", "gemini-2.5-flash"),
    ],
)
def test_committed_catalog_matches_stored_names_in_either_form(provider, stored_name, expected):
    model = CatalogRepository.default().model(ModelKind.LLM, provider, stored_name)

    assert model is not None and model.name == expected
