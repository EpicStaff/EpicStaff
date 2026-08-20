"""Regression guard for the cross-org secret read through `fill_with_defaults()`.

This is the brief's *second* named bypass path (the first is the
`init-realtime` `config` dict, covered by
`tests/api_tests/test_init_realtime_cross_org_secret.py`): `DefaultAgentConfig`
is an installation-wide singleton (`DefaultBaseModel.save()` forces `pk=1`),
not an `OrgScopedModel`. Its `llm_config` FK points at whichever org's
`LLMConfig` an admin last attached to it. `Agent.fill_with_defaults()` stamps
that `llm_config` onto any agent that has none of its own, with no regard for
which org the agent belongs to.

Before org-scoped resolution, this meant an agent in *any* org with no
`llm_config` of its own would run with the installation default's org's Secret
decrypted in plaintext. After this change, resolution now fails closed
instead: `SecretResolver` sees the default's Secret as `org_id`-mismatched and
raises, so realtime init errors rather than leaking another org's key -- the
same trade the `init-realtime` `config`-dict fix makes, applied to the
installation-default fallback instead of a request field.

`Agent.fill_with_defaults()` is exercised through the live realtime chat path
(`RealtimeService.init_realtime` -> `ConverterService.convert_rt_agent_chat_to_pydantic`)
-- the surviving caller of that method now that the CrewAI Crew/CrewNode
execution path is gone. The service is called directly rather than through
`POST /api/init-realtime/` to keep this test independent of the view layer.
"""

import pytest

from tables.models import LLMConfig, LLMModel, Provider
from tables.models.crew_models import DefaultAgentConfig
from tables.models.rbac_models import Organization
from tables.services.realtime_service import RealtimeService
from tables.services.secrets import secret_service

FOREIGN_DEFAULT_PLAINTEXT = "sk-DEFAULT-CONFIG-FOREIGN-ORG-7c2e"


@pytest.fixture
def org_owning_the_default(db):
    return Organization.objects.create(name="Org Owns Installation Default")


@pytest.fixture
def installation_default_pointing_at_a_foreign_secret(org_owning_the_default):
    """`DefaultAgentConfig` is a singleton (`pk=1`) shared by every org in the
    installation; its `llm_config` belongs to whichever org last attached it."""
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = LLMModel.objects.create(name="gpt-4o-default-cfg", llm_provider=provider)
    secret = secret_service.create(
        text=FOREIGN_DEFAULT_PLAINTEXT,
        org=org_owning_the_default,
        name="default-cfg-key",
    )
    llm_config = LLMConfig.objects.create(
        custom_name="installation-default-cfg",
        model=model,
        org=org_owning_the_default,
        api_key_secret=secret,
    )
    default_agent_config = DefaultAgentConfig(llm_config=llm_config)
    default_agent_config.save()
    return default_agent_config


@pytest.fixture
def agent_with_configured_realtime_missing_llm_config(
    wikipedia_agent_with_configured_realtime,
):
    """`fill_with_defaults()` is the only thing that gives this agent an
    `llm_config`, and it has no way to know which org owns the fallback."""
    agent = wikipedia_agent_with_configured_realtime
    agent.llm_config = None
    agent.save()
    return agent


@pytest.mark.django_db
class TestInstallationDefaultCannotLeakAcrossOrgs:
    def test_default_llm_configs_secret_never_reaches_a_foreign_orgs_session(
        self,
        installation_default_pointing_at_a_foreign_secret,
        agent_with_configured_realtime_missing_llm_config,
        default_org,
        redis_client_mock,
    ):
        agent = agent_with_configured_realtime_missing_llm_config

        # This is the fail-closed trade the org filter makes: a realtime init
        # whose agent falls back to another org's default config now errors
        # instead of silently decrypting that org's Secret.
        with pytest.raises(Exception, match="could not be resolved"):
            RealtimeService().init_realtime(
                agent_id=agent.pk, config={}, org_id=default_org.id
            )

        published = "".join(
            str(call) for call in redis_client_mock.publish.call_args_list
        )
        assert (
            FOREIGN_DEFAULT_PLAINTEXT not in published
        ), "the foreign org's plaintext key leaked into the published payload"
