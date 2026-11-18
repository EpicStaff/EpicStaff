import pytest
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.strategies.configs import SystemOneConfigStrategy
from tables.models import LLMConfig, SystemOneConfig
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_export_never_carries_the_secret(acme):
    secret = secret_service.create(text="ts-key", org=acme, name="TS")
    config = SystemOneConfig.objects.create(
        custom_name="jev",
        provider="typesafe",
        model_name="jev-1.14.0",
        api_key_secret=secret,
        org=acme,
    )

    data = SystemOneConfigStrategy().export_entity(config)

    assert "api_key_secret" not in data and "api_key_secret_id" not in data
    assert data["model_name"] == "jev-1.14.0"


@pytest.mark.django_db
def test_llm_backed_config_depends_on_its_llm_config(acme):
    llm_config = LLMConfig.objects.create(custom_name="llm", org=acme)
    config = SystemOneConfig.objects.create(
        custom_name="s1", provider="llm", llm_config=llm_config, org=acme
    )

    assert SystemOneConfigStrategy().extract_dependencies_from_instance(config) == {
        EntityType.LLM_CONFIG: [llm_config.id]
    }


@pytest.mark.django_db
def test_typesafe_config_has_no_dependencies(acme):
    config = SystemOneConfig.objects.create(
        custom_name="jev", provider="typesafe", model_name="jev-1.14.0", org=acme
    )

    assert SystemOneConfigStrategy().extract_dependencies_from_instance(config) == {}


@pytest.mark.django_db
def test_import_remaps_the_llm_config_into_the_target_org(acme, beta):
    source_llm = LLMConfig.objects.create(custom_name="llm", org=beta)
    target_llm = LLMConfig.objects.create(custom_name="llm", org=acme)
    id_mapper = IDMapper()
    id_mapper.map(EntityType.LLM_CONFIG, source_llm.id, target_llm.id)

    created = SystemOneConfigStrategy().create_entity(
        {"custom_name": "s1", "provider": "llm", "model_name": None, "llm_config": source_llm.id},
        id_mapper,
        org_id=acme.id,
    )

    assert (created.org_id, created.llm_config_id) == (acme.id, target_llm.id)


@pytest.mark.django_db
def test_import_drops_an_unmapped_llm_config(acme, beta):
    stray = LLMConfig.objects.create(custom_name="stray", org=beta)

    created = SystemOneConfigStrategy().create_entity(
        {"custom_name": "s1", "provider": "llm", "model_name": None, "llm_config": stray.id},
        IDMapper(),
        org_id=acme.id,
    )

    assert created.llm_config_id is None


@pytest.mark.django_db
def test_imported_typesafe_config_lands_without_a_key(acme):
    created = SystemOneConfigStrategy().create_entity(
        {"custom_name": "jev", "provider": "typesafe", "model_name": "jev-1.14.0", "llm_config": None},
        IDMapper(),
        org_id=acme.id,
    )

    assert created.api_key_secret_id is None


@pytest.mark.django_db
def test_import_refuses_an_unknown_jev_version(acme):
    with pytest.raises(ValidationError) as error:
        SystemOneConfigStrategy().create_entity(
            {"custom_name": "jev", "provider": "typesafe", "model_name": "jev-9.9.9", "llm_config": None},
            IDMapper(),
            org_id=acme.id,
        )

    assert "model_name" in error.value.detail


@pytest.mark.django_db
def test_import_renames_a_clashing_name_in_the_target_org(acme):
    SystemOneConfig.objects.create(
        custom_name="jev", provider="typesafe", model_name="jev-1.13.0", org=acme
    )

    created = SystemOneConfigStrategy().create_entity(
        {"custom_name": "jev", "provider": "typesafe", "model_name": "jev-1.14.0", "llm_config": None},
        IDMapper(),
        org_id=acme.id,
    )

    assert created.custom_name != "jev"
    assert SystemOneConfig.objects.filter(org=acme).count() == 2


@pytest.mark.django_db
def test_find_existing_never_reuses_another_orgs_config(acme, beta):
    SystemOneConfig.objects.create(
        custom_name="jev", provider="typesafe", model_name="jev-1.14.0", org=beta
    )
    data = {"custom_name": "jev", "provider": "typesafe", "model_name": "jev-1.14.0", "llm_config": None}

    assert SystemOneConfigStrategy().find_existing(data, IDMapper(), org_id=acme.id) is None


@pytest.mark.django_db
def test_find_existing_reuses_the_same_org_config(acme):
    existing = SystemOneConfig.objects.create(
        custom_name="jev", provider="typesafe", model_name="jev-1.14.0", org=acme
    )
    data = {"custom_name": "jev", "provider": "typesafe", "model_name": "jev-1.14.0", "llm_config": None}

    assert SystemOneConfigStrategy().find_existing(data, IDMapper(), org_id=acme.id) == existing


@pytest.mark.django_db
def test_find_existing_tells_llm_backed_configs_apart_by_their_mapped_llm_config(acme, beta):
    llm_a = LLMConfig.objects.create(custom_name="a", org=acme)
    llm_b = LLMConfig.objects.create(custom_name="b", org=acme)
    config_b = SystemOneConfig.objects.create(
        custom_name="s1", provider="llm", llm_config=llm_b, org=acme
    )
    source_llm = LLMConfig.objects.create(custom_name="src", org=beta)
    data = {"custom_name": "s1", "provider": "llm", "model_name": None, "llm_config": source_llm.id}

    id_mapper = IDMapper()
    id_mapper.map(EntityType.LLM_CONFIG, source_llm.id, llm_a.id)
    assert SystemOneConfigStrategy().find_existing(data, id_mapper, org_id=acme.id) is None

    id_mapper = IDMapper()
    id_mapper.map(EntityType.LLM_CONFIG, source_llm.id, llm_b.id)
    assert SystemOneConfigStrategy().find_existing(data, id_mapper, org_id=acme.id) == config_b


@pytest.mark.django_db
def test_import_refuses_a_jev_version_on_an_llm_backed_config(acme):
    with pytest.raises(ValidationError) as error:
        SystemOneConfigStrategy().create_entity(
            {"custom_name": "s1", "provider": "llm", "model_name": "jev-1.14.0", "llm_config": None},
            IDMapper(),
            org_id=acme.id,
        )

    assert "model_name" in error.value.detail


@pytest.mark.django_db
def test_import_refuses_a_mapped_llm_config_on_a_typesafe_config(acme, beta):
    source_llm = LLMConfig.objects.create(custom_name="llm", org=beta)
    target_llm = LLMConfig.objects.create(custom_name="llm", org=acme)
    id_mapper = IDMapper()
    id_mapper.map(EntityType.LLM_CONFIG, source_llm.id, target_llm.id)

    with pytest.raises(ValidationError) as error:
        SystemOneConfigStrategy().create_entity(
            {
                "custom_name": "jev",
                "provider": "typesafe",
                "model_name": "jev-1.14.0",
                "llm_config": source_llm.id,
            },
            id_mapper,
            org_id=acme.id,
        )

    assert "llm_config" in error.value.detail


@pytest.mark.django_db
def test_exported_openai_config_imports_without_a_key(acme):
    secret = secret_service.create(text="oa-key", org=acme, name="OA")
    config = SystemOneConfig.objects.create(
        custom_name="luna", provider="openai", model_name="gpt-6-luna", api_key_secret=secret, org=acme
    )
    data = SystemOneConfigStrategy().export_entity(config)
    data["custom_name"] = "luna-copy"

    created = SystemOneConfigStrategy().create_entity(data, IDMapper(), org_id=acme.id)

    assert (created.provider, created.model_name) == ("openai", "gpt-6-luna")
    assert created.api_key_secret_id is None


@pytest.mark.django_db
def test_import_refuses_a_jev_version_on_an_openai_config(acme):
    with pytest.raises(ValidationError) as error:
        SystemOneConfigStrategy().create_entity(
            {"custom_name": "luna", "provider": "openai", "model_name": "jev-1.14.0", "llm_config": None},
            IDMapper(),
            org_id=acme.id,
        )

    assert "model_name" in error.value.detail
