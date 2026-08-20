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
raises, so the session errors rather than leaking another org's key -- the
same trade the `init-realtime` fix makes, applied to a singleton row instead
of a request field.
"""

import pytest

from tables.models import (
    Agent,
    Crew,
    Graph,
    LLMConfig,
    LLMModel,
    Provider,
    Session,
    Task,
)
from tables.models.crew_models import DefaultAgentConfig
from tables.models.graph_models import CrewNode, Edge, StartNode
from tables.models.rbac_models import Organization
from tables.services.secrets import secret_service
from tables.services.session_manager_service import SessionManagerService

FOREIGN_DEFAULT_PLAINTEXT = "sk-DEFAULT-CONFIG-FOREIGN-ORG-7c2e"


@pytest.fixture
def org_owning_the_default(db):
    return Organization.objects.create(name="Org Owns Installation Default")


@pytest.fixture
def org_running_the_graph(db):
    return Organization.objects.create(name="Org Runs The Graph")


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
def graph_with_agent_missing_its_own_llm_config(org_running_the_graph):
    """An agent with no `llm_config` of its own: `fill_with_defaults()` is the
    only thing that gives it one, and it has no way to know which org owns it."""
    agent = Agent.objects.create(
        role="no-llm-config-agent",
        goal="rely on the installation default",
        backstory="none",
        llm_config=None,
        org=org_running_the_graph,
    )
    crew = Crew.objects.create(name="default-cfg-crew", org=org_running_the_graph)
    crew.agents.set([agent])
    # converter_service asserts a crew has at least one task before building
    # its payload, so the graph is not convertible without this.
    Task.objects.create(
        crew=crew,
        agent=agent,
        name="default-cfg-task",
        instructions="do nothing",
        expected_output="nothing",
        order=1,
    )

    graph = Graph.objects.create(name="default-cfg-graph", org=org_running_the_graph)
    # StartNode.node_name is a fixed "__start__" property, not a column.
    start = StartNode.objects.create(graph=graph, variables={"variables": {}})
    crew_node = CrewNode.objects.create(graph=graph, crew=crew, node_name="crew_node")
    # Without an edge off the start node, conversion raises
    # GraphEntryPointException before any payload is built.
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=crew_node.pk)
    return graph


@pytest.mark.django_db
class TestInstallationDefaultCannotLeakAcrossOrgs:
    def test_default_llm_configs_secret_never_reaches_a_foreign_orgs_session(
        self,
        installation_default_pointing_at_a_foreign_secret,
        graph_with_agent_missing_its_own_llm_config,
        monkeypatch,
    ):
        graph = graph_with_agent_missing_its_own_llm_config
        published = []
        service = SessionManagerService()
        monkeypatch.setattr(
            service.redis_service.redis_client,
            "publish",
            lambda channel, message: published.append(message) or 2,
        )

        # This is the fail-closed trade the org filter makes: a session whose
        # agent falls back to another org's default config now errors instead
        # of silently decrypting that org's Secret.
        with pytest.raises(Exception):
            service.run_session(graph_id=graph.pk, variables={})

        session = Session.objects.filter(graph_id=graph.pk).latest("pk")
        assert session.status == Session.SessionStatus.ERROR
        # Pin the specific cause: SecretResolver's org filter, not some other
        # unrelated failure in fill_with_defaults() or graph conversion.
        assert "could not be resolved" in session.status_data["reason"]
        assert (
            not published
        ), "a foreign org's default-config secret was published to the wire"
        assert FOREIGN_DEFAULT_PLAINTEXT not in str(
            session.status_data
        ), "the foreign org's plaintext key leaked into the session's error message"
