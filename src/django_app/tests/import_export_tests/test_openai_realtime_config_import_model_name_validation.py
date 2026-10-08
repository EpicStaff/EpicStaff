"""Coverage for `OpenAIRealtimeModelNameValidationMixin.validate_model_name`
on the REAL import path -- through
`OpenAIRealtimeConfigStrategy.create_entity`, not an isolated serializer
instantiation.

Until this fix, `create_entity` built the serializer with no `context=`, so
`validate_model_name` always saw `request = None` on create and silently
skipped validation -- any `model_name` sailed through import unchecked. The
fix reads `org` straight from the submitted data first (the import strategies
already put it there before building the serializer), falling back to the
request only for the live API path, where `org` is read-only and never part
of the payload.
"""

import pytest
from rest_framework.exceptions import ValidationError

from tables.import_export.id_mapper import IDMapper
from tables.import_export.strategies.configs import OpenAIRealtimeConfigStrategy
from tables.models import Provider, RealtimeModel

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
def test_create_entity_with_unregistered_model_name_is_now_rejected(
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
def test_create_entity_rejects_another_orgs_custom_model_name(default_org, openai_provider):
    from rbac.models import Organization

    other_org = Organization.objects.create(name="Other Org")
    RealtimeModel.objects.create(
        name="other-org-custom-model", provider=openai_provider, is_custom=True, org=other_org
    )
    strategy = OpenAIRealtimeConfigStrategy()
    with pytest.raises(ValidationError):
        strategy.create_entity(
            {"custom_name": "cfg", "model_name": "other-org-custom-model"},
            IDMapper(),
            org_id=default_org.id,
        )


@pytest.mark.django_db
def test_create_entity_without_provider_registered_is_rejected(default_org):
    # No Provider("openai") seeded at all -- matches the current validator's
    # existing (strict) behavior for an unconfigured registry; this test is
    # not about this fix, it just pins that behavior so a future change to it
    # is deliberate rather than accidental.
    strategy = OpenAIRealtimeConfigStrategy()
    with pytest.raises(ValidationError):
        strategy.create_entity(
            {"custom_name": "cfg", "model_name": VALID_MODEL_NAME},
            IDMapper(),
            org_id=default_org.id,
        )
    assert not Provider.objects.filter(name="openai").exists()
