"""Tests for LLMConfigData.to_litellm_kwargs and the LLMConfig -> LLMConfigData mapper."""

import pytest

from src.shared.models import LLMConfigData
from src.shared.models.ai_providers import LITELLM_GENERATION_FIELDS
from tables.models import LLMConfig, Provider
from tables.models.llm_models import LLMModel
from tables.services.converter_service import ConverterService

# Fields that configure where and how the request is sent, never generation
# behaviour. A new LLMConfigData field must be added here or to
# LITELLM_GENERATION_FIELDS; the completeness test fails until it is.
TRANSPORT_FIELDS = {
    "model",
    "base_url",
    "api_version",
    "api_key",
    "api_key_secret_id",
    "deployment_id",
    "extra_headers",
}


def test_every_config_field_is_classified():
    assert set(LLMConfigData.model_fields) == set(LITELLM_GENERATION_FIELDS) | TRANSPORT_FIELDS
    assert not set(LITELLM_GENERATION_FIELDS) & TRANSPORT_FIELDS


def test_unset_fields_are_omitted():
    assert LLMConfigData(model="gpt-4o").to_litellm_kwargs() == {}


def test_set_fields_are_passed():
    config = LLMConfigData(
        model="o3-mini",
        temperature=0.0,
        stop=["END"],
        logit_bias={50256: -100.0},
        seed=0,
        reasoning_effort="none",
    )

    assert config.to_litellm_kwargs() == {
        "temperature": 0.0,
        "stop": ["END"],
        "logit_bias": {50256: -100.0},
        "seed": 0,
        "reasoning_effort": "none",
    }


def test_transport_fields_are_never_present():
    config = LLMConfigData(
        model="gpt-4o",
        base_url="https://example.test",
        api_version="2024-10-21",
        api_key="sk-secret",
        api_key_secret_id=5,
        deployment_id="deployment",
        extra_headers={"X-Trace": "1"},
        temperature=0.4,
    )

    assert config.to_litellm_kwargs() == {"temperature": 0.4}


def test_exclude_drops_named_fields():
    config = LLMConfigData(model="o3-mini", stop=["END"], timeout=30, reasoning_effort="low")

    assert config.to_litellm_kwargs(exclude={"stop", "timeout"}) == {"reasoning_effort": "low"}


@pytest.mark.django_db
class TestConvertLLMConfigData:
    @pytest.fixture
    def model(self, db):
        provider, _ = Provider.objects.get_or_create(name="openai")
        yield LLMModel.objects.create(
            name="o3-mini",
            llm_provider=provider,
            base_url="https://example.test",
            api_version="2024-10-21",
            deployment_id="o3-deployment",
        )

    def test_reasoning_effort_is_mapped(self, model, default_org):
        config = LLMConfig.objects.create(
            custom_name="c", model=model, org=default_org, reasoning_effort="high"
        )

        data = ConverterService().convert_llm_config_data(config)

        assert data.reasoning_effort == "high"
        assert data.to_litellm_kwargs()["reasoning_effort"] == "high"
        assert data.model == "o3-mini"
        assert data.deployment_id == "o3-deployment"
        assert data.base_url == "https://example.test"
        assert data.api_version == "2024-10-21"

    def test_null_effort_produces_no_kwarg(self, model, default_org):
        config = LLMConfig.objects.create(custom_name="c", model=model, org=default_org)

        data = ConverterService().convert_llm_config_data(config)

        assert data.reasoning_effort is None
        assert "reasoning_effort" not in data.to_litellm_kwargs()

    def test_model_without_provider_converts(self, default_org):
        orphan_model = LLMModel.objects.create(name="orphan", llm_provider=None)
        config = LLMConfig.objects.create(custom_name="c", model=orphan_model, org=default_org)

        data = ConverterService().convert_llm_config_data(config)

        assert data.model == "orphan"

    def test_session_payload_carries_reasoning_effort(self, model, default_org):
        config = LLMConfig.objects.create(
            custom_name="c", model=model, org=default_org, reasoning_effort="low"
        )

        llm_data = ConverterService().convert_llm_config_to_pydantic(config)

        assert llm_data.provider == "openai"
        assert llm_data.config.reasoning_effort == "low"
        assert llm_data.model_dump()["config"]["reasoning_effort"] == "low"
