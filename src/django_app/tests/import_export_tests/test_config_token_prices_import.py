"""LLM config token prices travel through import/export; an export made before the
price columns existed imports as null and still matches its existing config."""

from copy import deepcopy

import pytest
from rest_framework.exceptions import ValidationError

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.models import LLMConfig

PRICE_FIELDS = ("input_cost_per_token", "output_cost_per_token")


@pytest.fixture
def llm_config_to_export(gpt_4o_llm, default_org):
    return LLMConfig.objects.create(
        custom_name="ImportPricedLLM", model=gpt_4o_llm, org=default_org
    )


@pytest.fixture
def strategy():
    return entity_registry.get_strategy(EntityType.LLM_CONFIG)


def _identity_mapper(export_data) -> IDMapper:
    mapper = IDMapper()
    for entity_type, entities in export_data.items():
        if isinstance(entities, list):
            for entity in entities:
                if isinstance(entity, dict) and "id" in entity:
                    mapper.map(entity_type, entity["id"], entity["id"], was_created=False)
    return mapper


def _export(export_service, config) -> tuple[dict, dict]:
    export_data = export_service.export_entities(EntityType.LLM_CONFIG, [config.id])
    return export_data, deepcopy(export_data[EntityType.LLM_CONFIG][0])


def _set_prices(config, value) -> None:
    for field in PRICE_FIELDS:
        setattr(config, field, value)
    config.save(update_fields=list(PRICE_FIELDS))


@pytest.mark.django_db
def test_prices_round_trip(export_service, default_org, strategy, llm_config_to_export):
    _set_prices(llm_config_to_export, 0.0000025)
    export_data, config_data = _export(export_service, llm_config_to_export)

    new_config = strategy.create_entity(
        config_data, _identity_mapper(export_data), org_id=default_org.id
    )

    new_config.refresh_from_db()
    assert new_config.pk != llm_config_to_export.pk
    for field in PRICE_FIELDS:
        assert config_data[field] == 0.0000025
        assert getattr(new_config, field) == 0.0000025


@pytest.mark.django_db
def test_export_without_prices_imports_as_null(
    export_service, default_org, strategy, llm_config_to_export
):
    export_data, config_data = _export(export_service, llm_config_to_export)
    for field in PRICE_FIELDS:
        config_data.pop(field)

    new_config = strategy.create_entity(
        config_data, _identity_mapper(export_data), org_id=default_org.id
    )

    new_config.refresh_from_db()
    for field in PRICE_FIELDS:
        assert getattr(new_config, field) is None


@pytest.mark.django_db
@pytest.mark.parametrize("drop_fields", [False, True], ids=["current", "pre-prices"])
def test_reimport_finds_the_existing_config(
    export_service, default_org, strategy, llm_config_to_export, drop_fields
):
    export_data, config_data = _export(export_service, llm_config_to_export)
    if drop_fields:
        for field in PRICE_FIELDS:
            config_data.pop(field)

    found = strategy.find_existing(
        config_data, _identity_mapper(export_data), org_id=default_org.id
    )

    assert found is not None
    assert found.id == llm_config_to_export.id


@pytest.mark.django_db
def test_reimport_of_a_priced_config_finds_it(
    export_service, default_org, strategy, llm_config_to_export
):
    _set_prices(llm_config_to_export, 0.0000025)
    export_data, config_data = _export(export_service, llm_config_to_export)

    found = strategy.find_existing(
        config_data, _identity_mapper(export_data), org_id=default_org.id
    )

    assert found is not None
    assert found.id == llm_config_to_export.id


@pytest.mark.django_db
def test_reimport_with_a_different_price_does_not_match(
    export_service, default_org, strategy, llm_config_to_export
):
    export_data, config_data = _export(export_service, llm_config_to_export)
    for field in PRICE_FIELDS:
        config_data[field] = 0.5

    found = strategy.find_existing(
        config_data, _identity_mapper(export_data), org_id=default_org.id
    )

    assert found is None


@pytest.mark.django_db
def test_import_with_only_one_price_is_rejected(
    export_service, default_org, strategy, llm_config_to_export
):
    export_data, config_data = _export(export_service, llm_config_to_export)
    config_data["input_cost_per_token"] = 0.1
    count_before = LLMConfig.objects.count()

    with pytest.raises(ValidationError) as error:
        strategy.create_entity(config_data, _identity_mapper(export_data), org_id=default_org.id)

    assert "output_cost_per_token" in error.value.detail
    assert LLMConfig.objects.count() == count_before
