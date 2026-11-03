"""`OpenAIRealtimeConfig` model_name validation on the import path (the
request-less `context["org_id"]` branch of
`OpenAIRealtimeModelNameValidationMixin`).
"""

import pytest
from rest_framework.exceptions import ValidationError

from tables.import_export.id_mapper import IDMapper
from tables.import_export.strategies.configs import OpenAIRealtimeConfigStrategy
from tables.models import Provider, RealtimeModel
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DEAD_MODEL_NAME = "gpt-4o-realtime-preview-2024-12-17"
VALID_MODEL_NAME = "gpt-realtime-1.5"

# `openai_realtime_builtin_model` fixture is shared, defined in tests/fixtures.py


@pytest.mark.django_db
def test_create_entity_with_registered_model_name_succeeds(
    default_org, openai_realtime_builtin_model
):
    strategy = OpenAIRealtimeConfigStrategy()
    instance = strategy.create_entity(
        {"custom_name": "cfg", "model_name": VALID_MODEL_NAME},
        IDMapper(),
        org_id=default_org.id,
    )
    assert instance.model_name == VALID_MODEL_NAME
    assert instance.org_id == default_org.id


@pytest.mark.django_db
def test_create_entity_with_unregistered_model_name_is_rejected(
    default_org, openai_realtime_builtin_model
):
    strategy = OpenAIRealtimeConfigStrategy()
    with pytest.raises(ValidationError) as exc_info:
        strategy.create_entity(
            {"custom_name": "cfg", "model_name": DEAD_MODEL_NAME},
            IDMapper(),
            org_id=default_org.id,
        )
    assert "model_name" in exc_info.value.detail


@pytest.mark.django_db
def test_create_entity_with_org_custom_model_name_succeeds(default_org, openai_provider):
    RealtimeModel.objects.create(
        name="org-custom-model", provider=openai_provider, is_custom=True, org=default_org
    )
    strategy = OpenAIRealtimeConfigStrategy()
    instance = strategy.create_entity(
        {"custom_name": "cfg", "model_name": "org-custom-model"},
        IDMapper(),
        org_id=default_org.id,
    )
    assert instance.model_name == "org-custom-model"


@pytest.mark.django_db
def test_create_entity_rejects_another_orgs_custom_model_name(default_org, openai_provider, beta):
    RealtimeModel.objects.create(
        name="foreign-org-custom-model", provider=openai_provider, is_custom=True, org=beta
    )
    strategy = OpenAIRealtimeConfigStrategy()
    with pytest.raises(ValidationError):
        strategy.create_entity(
            {"custom_name": "cfg", "model_name": "foreign-org-custom-model"},
            IDMapper(),
            org_id=default_org.id,
        )


@pytest.mark.django_db
def test_create_entity_without_provider_registered_is_rejected(default_org):
    strategy = OpenAIRealtimeConfigStrategy()
    with pytest.raises(ValidationError):
        strategy.create_entity(
            {"custom_name": "cfg", "model_name": VALID_MODEL_NAME},
            IDMapper(),
            org_id=default_org.id,
        )
    assert not Provider.objects.filter(name="openai").exists()
