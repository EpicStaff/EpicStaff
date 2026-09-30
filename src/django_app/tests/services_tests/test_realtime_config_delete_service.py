"""Service-level tests for the three realtime provider config delete services.

The three share one collector, parametrised by the FK name, so every test runs
against all three -- a wrong `config_field` on any one subclass would fail here.
"""

import pytest

from agents.models import AgentDefinition
from tables.models import Agent
from tables.models.rbac_models import Organization
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)
from tables.services.delete_services import (
    ElevenLabsRealtimeConfigDeleteService,
    GeminiRealtimeConfigDeleteService,
    OpenAIRealtimeConfigDeleteService,
)
from tables.services.delete_services.realtime_config_delete_service import (
    _ProviderRealtimeConfigDeleteService,
)
from tables.services.delete_services.usage import RefKind, SkipEntry, SkipReason
from tables.services.rbac.effective_permissions import EffectivePermissions

PROVIDERS = [
    pytest.param(
        OpenAIRealtimeConfig,
        OpenAIRealtimeConfigDeleteService,
        "openai_config",
        id="openai",
    ),
    pytest.param(
        ElevenLabsRealtimeConfig,
        ElevenLabsRealtimeConfigDeleteService,
        "elevenlabs_config",
        id="elevenlabs",
    ),
    pytest.param(
        GeminiRealtimeConfig,
        GeminiRealtimeConfigDeleteService,
        "gemini_config",
        id="gemini",
    ),
]


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _permissions(*readable):
    return EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={rt.value: int(Permission.READ) for rt in readable},
    )


def _agents_bucket(result, config_id):
    (bucket,) = result.usage[config_id].buckets
    assert bucket.resource_type == ResourceType.AGENTS.value
    return bucket


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,service_class,fk", PROVIDERS)
def test_a_past_session_alone_does_not_block(org_a, config_model, service_class, fk):
    """RealtimeAgentChat is a session snapshot, not a dependency."""
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    RealtimeAgentChat.objects.create(connection_key="past-session", **{fk: config})

    result = service_class().bulk_delete([config.id], org_a.id, _permissions())

    assert result.deleted_ids == [config.id]
    assert result.skipped == []
    assert not config_model.objects.filter(id=config.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,service_class,fk", PROVIDERS)
def test_both_agent_kinds_are_reported(org_a, config_model, service_class, fk):
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    legacy = Agent.objects.create(org=org_a, role="legacy", goal="g", backstory="b")
    current = AgentDefinition.objects.create(organization=org_a, name="current")
    RealtimeAgent.objects.create(agent=legacy, **{fk: config})
    RealtimeAgentDefinition.objects.create(agent_definition=current, **{fk: config})

    result = service_class().bulk_delete(
        [config.id], org_a.id, _permissions(ResourceType.AGENTS), dry_run=True
    )

    agents = _agents_bucket(result, config.id)
    assert {(ref.kind, ref.id) for ref in agents.visible_refs} == {
        (RefKind.AGENT, legacy.id),
        (RefKind.AGENT_DEFINITION, current.id),
    }


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,service_class,fk", PROVIDERS)
def test_an_agent_the_caller_cannot_see_blocks(org_a, config_model, service_class, fk):
    """The deprecated RealtimeAgent -> tables.Agent path still counts."""
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    legacy = Agent.objects.create(org=org_a, role="legacy", goal="g", backstory="b")
    RealtimeAgent.objects.create(agent=legacy, **{fk: config})

    result = service_class().bulk_delete([config.id], org_a.id, _permissions())

    assert result.skipped == [
        SkipEntry(id=config.id, reason=SkipReason.IN_USE_RESTRICTED)
    ]
    assert config_model.objects.filter(id=config.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,service_class,fk", PROVIDERS)
def test_an_agent_definition_the_caller_cannot_see_blocks(
    org_a, config_model, service_class, fk
):
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    current = AgentDefinition.objects.create(organization=org_a, name="current")
    RealtimeAgentDefinition.objects.create(agent_definition=current, **{fk: config})

    result = service_class().bulk_delete([config.id], org_a.id, _permissions())

    assert result.skipped == [
        SkipEntry(id=config.id, reason=SkipReason.IN_USE_RESTRICTED)
    ]
    assert config_model.objects.filter(id=config.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,service_class,fk", PROVIDERS)
def test_another_orgs_config_is_not_found(
    org_a, org_b, config_model, service_class, fk
):
    other = config_model.objects.create(org=org_b, custom_name="other")

    result = service_class().bulk_delete(
        [other.id], org_a.id, _permissions(ResourceType.AGENTS)
    )

    assert result.not_found_ids == [other.id]
    assert result.deleted_ids == []
    assert config_model.objects.filter(id=other.id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("config_model,service_class,fk", PROVIDERS)
def test_another_orgs_agents_are_not_usage(
    org_a, org_b, config_model, service_class, fk
):
    """Both agent sources filter the referencing row by org.

    Cross-org references cannot be created through the API, but the guard must
    not depend on that: its own org filter keeps another org's agent names out.
    """
    config = config_model.objects.create(org=org_a, custom_name="cfg")
    legacy = Agent.objects.create(org=org_b, role="foreign", goal="g", backstory="b")
    current = AgentDefinition.objects.create(organization=org_b, name="foreign")
    RealtimeAgent.objects.create(agent=legacy, **{fk: config})
    RealtimeAgentDefinition.objects.create(agent_definition=current, **{fk: config})

    preview = service_class().bulk_delete(
        [config.id], org_a.id, _permissions(ResourceType.AGENTS), dry_run=True
    )
    assert _agents_bucket(preview, config.id).total_count == 0

    result = service_class().bulk_delete([config.id], org_a.id, _permissions())
    assert result.deleted_ids == [config.id]


def test_the_shared_base_cannot_be_instantiated():
    """It sets no `model`, so using it directly fails at once, not mid-delete."""
    with pytest.raises(TypeError):
        _ProviderRealtimeConfigDeleteService()
