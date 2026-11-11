import pytest

from src.shared.models import (
    AgentDefinitionData,
    AgentSpec,
    LLMConfigData,
    LLMData,
)
from tables.services.converter_service import ConverterService


@pytest.mark.django_db
def test_converter_carries_config_name(llm_config):
    data = ConverterService().convert_llm_config_data(llm_config)
    assert data.custom_name == "MyGPT-4o"


def test_config_name_never_reaches_litellm():
    config = LLMConfigData(model="gpt-4o", temperature=0.2, custom_name="Key A")
    kwargs = config.to_litellm_kwargs(provider="openai")
    assert kwargs == {"temperature": 0.2}


def test_config_name_defaults_to_none():
    assert LLMConfigData(model="gpt-4o").custom_name is None


def test_fallback_fields_default_to_none():
    definition = AgentDefinitionData(id=1, name="a")
    assert definition.fallback_llm_config_id is None
    assert definition.fallback_llm is None
    assert definition.fallback_llm_warning is None

    primary = LLMData(provider="openai", config=LLMConfigData(model="gpt-4o"))
    assert AgentSpec(id=1, name="a", instructions="", llm=primary).fallback_llm is None
