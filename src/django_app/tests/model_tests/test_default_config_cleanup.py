import pytest

from tables.models.llm_models import LLMConfig, LLMModel
from rbac.models import Organization


@pytest.mark.django_db
def test_llm_config_fill_with_defaults_does_not_raise():
    org = Organization.objects.create(name="Org FillDefaults")
    model = LLMModel.objects.create(name="gpt-4o", llm_provider=None)
    config = LLMConfig(org=org, custom_name="test-config", model=model)
    config.fill_with_defaults()  # would raise AttributeError before this task
    assert config.temperature is not None  # still fills other defaultable fields
