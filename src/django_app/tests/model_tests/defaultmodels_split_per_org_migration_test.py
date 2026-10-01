from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.db import connection
from rbac.models import Organization
from tables.models.default_models import DefaultModels
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig

split_migration = import_module("tables.migrations.0253_split_defaultmodels_per_org")


@pytest.fixture
def allow_ownerless_default_models(db):
    """Recreate the pre-0254 schema so the legacy ownerless row can exist.

    Postgres DDL is transactional: the test transaction's rollback restores NOT NULL.
    """
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE tables_defaultmodels ALTER COLUMN org_id DROP NOT NULL;")
    yield


@pytest.mark.django_db
def test_split_gives_each_owning_org_a_row_with_only_its_own_configs(
    allow_ownerless_default_models,
):
    org_a = Organization.objects.create(name="Split Org A")
    org_b = Organization.objects.create(name="Split Org B")
    llm_config_a = LLMConfig.objects.create(custom_name="llm-a", org=org_a)
    embedding_config_a = EmbeddingConfig.objects.create(custom_name="embedding-a", org=org_a)
    llm_config_b = LLMConfig.objects.create(custom_name="llm-b", org=org_b)
    legacy_row = DefaultModels.objects.create(
        org=None,
        agent_llm_config=llm_config_a,
        memory_embedding_config=embedding_config_a,
        project_manager_llm_config=llm_config_b,
    )

    split_migration.split_defaultmodels_per_org(django_apps, None)

    assert not DefaultModels.objects.filter(pk=legacy_row.pk, org__isnull=True).exists()
    assert DefaultModels.objects.count() == 2
    row_a = DefaultModels.objects.get(org=org_a)
    assert row_a.agent_llm_config_id == llm_config_a.id
    assert row_a.memory_embedding_config_id == embedding_config_a.id
    assert row_a.project_manager_llm_config_id is None
    row_b = DefaultModels.objects.get(org=org_b)
    assert row_b.project_manager_llm_config_id == llm_config_b.id
    assert row_b.agent_llm_config_id is None
    assert row_b.memory_embedding_config_id is None


@pytest.mark.django_db
def test_split_drops_an_ownerless_row_that_references_no_config(
    allow_ownerless_default_models,
):
    DefaultModels.objects.create(org=None)

    split_migration.split_defaultmodels_per_org(django_apps, None)

    assert not DefaultModels.objects.exists()


@pytest.mark.django_db
def test_split_leaves_org_owned_rows_untouched_when_no_ownerless_row_exists():
    org = Organization.objects.create(name="Split Org")
    llm_config = LLMConfig.objects.create(custom_name="llm", org=org)
    owned_row = DefaultModels.objects.create(org=org, agent_llm_config=llm_config)

    split_migration.split_defaultmodels_per_org(django_apps, None)

    assert list(DefaultModels.objects.values_list("pk", "org_id", "agent_llm_config_id")) == [
        (owned_row.pk, org.id, llm_config.id)
    ]
