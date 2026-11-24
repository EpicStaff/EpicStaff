from dataclasses import replace

import pytest
from ai_models.domain.specs import ModelKind
from ai_models.management.commands import upload_models
from ai_models.models import EmbeddingModel, LLMConfig, LLMModel, Provider
from ai_models.repository import CatalogRepository
from rbac.models import Organization

from tests.ai_models_tests.factories import make_runtime_catalog


def _catalog_with_anthropic_alias():
    catalog = make_runtime_catalog()
    providers = {
        **catalog.providers,
        "anthropic": replace(catalog.providers["anthropic"], aliases=("anthropic_ai",)),
    }
    return replace(catalog, providers=providers)


@pytest.fixture
def catalog(monkeypatch):
    repository = CatalogRepository(_catalog_with_anthropic_alias())
    monkeypatch.setattr(CatalogRepository, "default", classmethod(lambda cls: repository))
    return repository


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org A")


def _seed():
    upload_models.upload_tags()
    upload_models.upload_providers()
    upload_models.upload_llm_models()
    upload_models.upload_embedding_models()


def _builtin_llm_rows():
    return {
        (row.llm_provider.name, row.name): row
        for row in LLMModel.objects.filter(org__isnull=True).select_related("llm_provider")
    }


@pytest.mark.django_db
def test_fresh_database_gets_a_row_per_catalog_model_of_a_provider_that_runs_the_kind(catalog):
    _seed()

    assert set(_builtin_llm_rows()) == {
        ("openai", "gpt-4o"),
        ("openai", "gpt-4o-mini"),
        # Deprecated: kept as a row, so configs on it keep working.
        ("openai", "gpt-3.5-turbo-0301"),
        ("openai", "gpt-7"),
        ("anthropic", "claude-sonnet"),
        ("bedrock", "anthropic.claude-v2"),
    }
    assert all(row.predefined and row.is_visible for row in _builtin_llm_rows().values())
    # bedrock and voyage have embedding models, but neither runs embedding.
    assert list(
        EmbeddingModel.objects.values_list("embedding_provider__name", "name", "org")
    ) == [("openai", "text-embedding-3-small", None)]
    # `mystery` has models but no registry entry: no rows, and no provider row.
    assert not Provider.objects.filter(name="mystery").exists()


@pytest.mark.django_db
def test_recommended_tag_follows_the_catalog(catalog):
    _seed()

    rows = _builtin_llm_rows()
    assert list(rows["openai", "gpt-4o"].tags.values_list("name", flat=True)) == ["recommended"]
    assert not rows["openai", "gpt-4o-mini"].tags.exists()


@pytest.mark.django_db
def test_rerun_is_idempotent(catalog):
    _seed()
    first = {key: (row.pk, row.is_visible) for key, row in _builtin_llm_rows().items()}
    provider_ids = sorted(Provider.objects.values_list("pk", flat=True))

    _seed()

    assert {key: (row.pk, row.is_visible) for key, row in _builtin_llm_rows().items()} == first
    assert sorted(Provider.objects.values_list("pk", flat=True)) == provider_ids


@pytest.mark.django_db
def test_removed_model_is_hidden_not_deleted(catalog, org):
    anthropic = Provider.objects.create(name="anthropic")
    retired = LLMModel.objects.create(name="claude-retired", llm_provider=anthropic, predefined=True)
    config = LLMConfig.objects.create(custom_name="Old", model=retired, org=org)

    _seed()

    retired.refresh_from_db()
    assert retired.is_visible is False
    assert LLMConfig.objects.get(pk=config.pk).model_id == retired.pk


@pytest.mark.django_db
def test_rows_of_a_provider_without_registry_entry_are_hidden(catalog):
    mystery = Provider.objects.create(name="mystery")
    row = LLMModel.objects.create(name="mystery-1", llm_provider=mystery, predefined=True)

    _seed()

    row.refresh_from_db()
    assert row.is_visible is False


@pytest.mark.django_db
def test_hidden_row_back_in_the_catalog_is_shown_again(catalog):
    openai = Provider.objects.create(name="openai")
    row = LLMModel.objects.create(
        name="gpt-4o-mini", llm_provider=openai, predefined=True, is_visible=False
    )

    _seed()

    row.refresh_from_db()
    assert row.is_visible is True


@pytest.mark.django_db
def test_existing_row_matches_by_lookup_name_and_keeps_its_name_and_id(catalog):
    anthropic = Provider.objects.create(name="anthropic")
    row = LLMModel.objects.create(
        name="anthropic/claude-sonnet", llm_provider=anthropic, predefined=True, is_visible=False
    )

    _seed()

    row.refresh_from_db()
    assert row.name == "anthropic/claude-sonnet" and row.is_visible is True
    assert LLMModel.objects.filter(llm_provider=anthropic).count() == 1


@pytest.mark.django_db
def test_provider_row_under_an_alias_is_reused_not_duplicated(catalog):
    alias_row = Provider.objects.create(name="anthropic_ai")
    LLMModel.objects.create(name="claude-sonnet", llm_provider=alias_row, predefined=True)

    _seed()
    _seed()

    assert not Provider.objects.filter(name="anthropic").exists()
    assert list(LLMModel.objects.filter(llm_provider=alias_row).values_list("name", flat=True)) == [
        "claude-sonnet"
    ]


@pytest.mark.django_db
def test_custom_org_models_untouched(catalog, org):
    openai = Provider.objects.create(name="openai")
    custom = LLMModel.objects.create(
        name="my-fine-tune", llm_provider=openai, org=org, is_custom=True, is_visible=True
    )
    # An org's custom row named like a catalog model is not adopted either.
    shadow = LLMModel.objects.create(
        name="gpt-4o", llm_provider=openai, org=org, is_custom=True, is_visible=False
    )

    _seed()

    custom.refresh_from_db()
    shadow.refresh_from_db()
    assert (custom.org_id, custom.is_custom, custom.is_visible, custom.predefined) == (
        org.pk,
        True,
        True,
        False,
    )
    assert (shadow.org_id, shadow.is_visible, shadow.predefined) == (org.pk, False, False)
    assert LLMModel.objects.filter(name="gpt-4o", org__isnull=True).count() == 1


@pytest.mark.django_db
def test_committed_catalog_seeds_llm_and_embedding_rows():
    upload_models.upload_tags()
    upload_models.upload_providers()
    upload_models.upload_llm_models()
    upload_models.upload_embedding_models()

    repository = CatalogRepository.default()
    for kind, model_class in ((ModelKind.LLM, LLMModel), (ModelKind.EMBEDDING, EmbeddingModel)):
        expected = sum(
            len(repository.models(kind, provider.name, include_deprecated=True))
            for provider in repository.providers(kind)
        )
        assert model_class.objects.filter(org__isnull=True, is_visible=True).count() == expected
    assert LLMModel.objects.filter(llm_provider__name="anthropic", org__isnull=True).exists()
