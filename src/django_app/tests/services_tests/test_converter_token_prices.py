import pytest

from rbac.models import Organization
from tables.models import LLMConfig, LLMModel, Provider
from tables.models.llm_models import DefaultLLMConfig
from tables.services.converter_service import ConverterService


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org ConverterPrices")


@pytest.fixture
def provider(db):
    return Provider.objects.get_or_create(name="openai")[0]


@pytest.mark.django_db
def test_llm_config_prices_reach_the_wire_model(org, provider):
    model = LLMModel.objects.create(name="gateway-model-priced", llm_provider=provider)
    config = LLMConfig.objects.create(
        custom_name="priced",
        model=model,
        org=org,
        input_cost_per_token=0.000001,
        output_cost_per_token=0.000004,
    )

    data = ConverterService().convert_llm_config_to_pydantic(config)

    assert data.config.input_cost_per_token == 0.000001
    assert data.config.output_cost_per_token == 0.000004


@pytest.mark.django_db
def test_unpriced_llm_config_stays_null_and_out_of_the_agent_dump(org, provider):
    model = LLMModel.objects.create(name="gateway-model-unpriced", llm_provider=provider)
    config = LLMConfig.objects.create(custom_name="unpriced", model=model, org=org)

    data = ConverterService().convert_llm_config_to_pydantic(config)

    assert data.config.input_cost_per_token is None
    assert data.config.output_cost_per_token is None
    # The agent builds its litellm kwargs from this dump.
    dumped = data.config.model_dump(exclude_none=True)
    assert "input_cost_per_token" not in dumped
    assert "output_cost_per_token" not in dumped


@pytest.mark.django_db
def test_fill_with_defaults_never_sets_a_price(org):
    default_config = DefaultLLMConfig.load()
    assert not hasattr(default_config, "input_cost_per_token")
    assert not hasattr(default_config, "output_cost_per_token")
    config = LLMConfig(org=org, custom_name="defaults")

    config.fill_with_defaults()

    assert config.input_cost_per_token is None
    assert config.output_cost_per_token is None
